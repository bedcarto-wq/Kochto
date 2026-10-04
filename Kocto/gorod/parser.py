"""Понимание фразы игрока в закрытом мире: текст → одна карточка (Card) + пояснения.

Без обучения и без «магии»: словарь основ из данных, выбор самой длинной основы,
явный отчёт о том, что понято и что угадано. Игрок подтверждает карточку до броска.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .engine import Card
from .nlu import fuzzy_prefix

AI_MIN_CONFIDENCE = 0.45

SLOT_RU = {"group": "группа", "proposal": "вопрос", "paper": "газета"}
WORD = re.compile(r"[а-яa-z0-9]+")


@dataclass
class Parse:
    card: Optional[Card]
    guessed: bool = False
    source: str = ""  # словарь | ИИ | догадка
    confidence: float = 0.0
    alternatives: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def tokens(text: str) -> List[str]:
    return WORD.findall((text or "").lower().replace("ё", "е"))


def _hit(tok: str, stem: str) -> bool:
    return tok == stem if len(stem) <= 2 else tok.startswith(stem)


def _match_at(toks: List[str], i: int, alias: str) -> int:
    """Длина совпадения (в токенах) многословной основы, начиная с позиции i; 0 — нет."""
    parts = alias.split()
    if i + len(parts) > len(toks):
        return 0
    return len(parts) if all(_hit(toks[i + k], p) for k, p in enumerate(parts)) else 0


def _entities(data: dict, toks: List[str]) -> List[Tuple[int, str, str]]:
    """[(позиция, вид, id)] — на каждой позиции побеждает самая длинная основа."""
    table = []
    for kind, key in (("group", "groups"), ("proposal", "proposals"), ("paper", "papers")):
        for eid, ent in data[key].items():
            for alias in ent["aliases"]:
                table.append((alias, kind, eid))
    table.sort(key=lambda t: (-len(t[0]), t[0]))
    out, i = [], 0
    while i < len(toks):
        for alias, kind, eid in table:
            n = _match_at(toks, i, alias)
            if n:
                out.append((i, kind, eid, False))
                i += n
                break
        else:
            for alias, kind, eid in table:
                if " " not in alias and fuzzy_prefix(toks[i], alias):
                    out.append((i, kind, eid, True))
                    break
            i += 1
    return out


def _actions(data: dict, toks: List[str]) -> List[str]:
    found = []
    for aid in data["action_priority"]:
        if any(_hit(t, s) for t in toks for s in data["lexicon"]["actions"][aid]):
            found.append(aid)
    return found


def _side(data: dict, toks: List[str]) -> Tuple[int, bool]:
    lex = data["lexicon"]
    for i, t in enumerate(toks):
        if any(_hit(t, s) for s in lex["negative"]):
            return -1, True
        if t == "не" and any(_hit(n, s) for n in toks[i + 1:i + 3] for s in lex["negatable"]):
            return -1, True
    if any(_hit(t, s) for t in toks for s in lex["positive"]):
        return 1, True
    return 1, False


def _deadline(data: dict, toks: List[str]) -> int:
    lex = data["lexicon"]
    for i, t in enumerate(toks):
        num = int(t) if t.isdigit() else lex["numbers"].get(t)
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        if num and nxt.startswith("нед"):
            return int(num)
        if num and any(nxt.startswith(m) for m in lex["month_words"]):
            return int(num) * 4
        if any(t.startswith(m) for m in lex["month_words"]) and not (i and (toks[i - 1].isdigit() or toks[i - 1] in lex["numbers"])):
            return 4
    return 0


_CACHE: dict = {}


def model(data: dict, learned=None):
    """Базовая модель + фразы кампании (подстройка во время игры). Кэшируется."""
    base = data.get("_nlu")
    if base is None or not learned:
        return base
    key = (id(base), tuple(tuple(x) for x in learned))
    if key not in _CACHE:
        _CACHE.clear()
        _CACHE[key] = base.extended([tuple(x) for x in learned], int(data["tuning"]["learned_weight"]))
    return _CACHE[key]


def _norm(text: str) -> str:
    return " ".join(tokens(text))


def parse(data: dict, text: str, learned=None) -> Parse:
    toks = tokens(text)
    if not toks:
        return Parse(None, notes=["пустая фраза"])
    ents = _entities(data, toks)
    by_kind = {"group": [], "proposal": [], "paper": []}
    notes, guessed = [], False
    for i, kind, eid, fuzzy in ents:
        if eid not in by_kind[kind]:
            by_kind[kind].append(eid)
        if fuzzy:
            notes.append("похоже на опечатку: «" + toks[i] + "» понято как «" + _label(data, kind, eid) + "»")
    acts = _actions(data, toks)
    m = model(data, learned)
    probs = m.predict(toks) if m is not None else None
    source, conf = "словарь", 1.0
    remembered = [a for t, a in (learned or []) if _norm(t) == _norm(text)]
    if remembered:
        action = remembered[-1]
        source = "память"
        acts = [action] + [a for a in acts if a != action]
        notes.append("эту фразу вы уже уточняли — " + data["actions"][action]["name"])
    elif len(acts) == 1:
        action = acts[0]
    elif acts:
        specific = [a for a in acts if a != "statement"] or acts  # «заявить» — общий глагол, уступает конкретному
        action = max(specific, key=lambda a: (probs or {}).get(a, 0.0)) if probs else specific[0]
        conf = (probs or {}).get(action, 0.0)
        acts = [action] + [a for a in acts if a != action]
    elif probs and max(probs.values()) >= AI_MIN_CONFIDENCE:
        action = max(probs, key=lambda a: (probs[a], a))
        source, conf, guessed = "ИИ", probs[action], True
        notes.append("понято по смыслу (ИИ, уверенность " + str(round(conf * 100)) + "%): "
                     + data["actions"][action]["name"])
    elif by_kind["paper"]:
        action, guessed = "interview", True
    elif by_kind["group"]:
        action, guessed = "meeting", True
    elif by_kind["proposal"]:
        action, guessed = "statement", True
    else:
        return Parse(None, notes=["не нашёл ни действия, ни группы, ни вопроса, ни газеты"])
    if guessed and source != "ИИ":
        source, conf = "догадка", 0.3
        notes.append("глагол действия не найден — предполагаю: " + data["actions"][action]["name"])
    generic_only = acts[1:] == ["statement"]  # «заявить об угрозах», «публично пообещать» — одно действие
    if len(acts) > 1 and not generic_only:
        notes.append("в фразе несколько действий; выполняется одно: " + data["actions"][action]["name"]
                     + ". Остальное — отдельной фразой")
    card = Card(action=action, text=text)
    for kind in ("group", "proposal", "paper"):
        if by_kind[kind]:
            setattr(card, kind, by_kind[kind][0])
            if len(by_kind[kind]) > 1:
                notes.append("упомянуто несколько (" + SLOT_RU[kind] + "), взято первое")
    if card.proposal:
        card.side, explicit = _side(data, toks)
        if not explicit:
            notes.append("позиция не указана явно — считаю «ЗА»")
    if action == "promise":
        card.deadline = _deadline(data, toks)
        if not card.deadline:
            notes.append("срок не назван — по умолчанию " + str(data["actions"]["promise"]["default_deadline"]) + " нед.")
    for kind in ("group", "proposal", "paper"):
        if getattr(card, kind) and kind not in data["actions"][action]["requires"] and action != "interview":
            notes.append("для действия «" + data["actions"][action]["name"] + "» " + SLOT_RU[kind] + " не учитывается")
    return Parse(card, guessed=guessed, alternatives=acts[1:], notes=notes, source=source,
                 confidence=round(conf, 3))


def _label(data: dict, kind: str, eid: str) -> str:
    return data[{"group": "groups", "proposal": "proposals", "paper": "papers"}[kind]][eid]["forms"]["im"]
