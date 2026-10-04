"""«Город помнит» — ядро MVP Кочто (stdlib-only).

Принципы:
  * одна фраза = одна карточка действия (Card); лишние слова не добавляют эффектов;
  * эффекты считаются из смысла карточки: группа × позиция по вопросу × значимость;
  * всё, что произошло, пишется в журнал фактов (Fact); тексты и соперник читают журнал;
  * обещания имеют сроки и проверяются каждую неделю;
  * выборы считаются по поддержке и доверию групп, с раскладкой по группам;
  * детерминизм — схема F: зерно недели хранится в сохранении, rng = Random(seed + offset);
  * ошибки данных — DataError, никаких тихих подстановок.
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

DATA_DIR = Path(__file__).resolve().parent / "data"
SCHEMA_VERSION = 1
SLOTS = ("group", "proposal", "paper")


class DataError(Exception):
    """Адресная ошибка данных: отсутствует файл, ключ или неверный тип."""


class RuleError(Exception):
    """Ход невозможен по правилам (нет действий, денег, слотов). Состояние не меняется."""


# ================= данные =================
def _need(obj, key, typ, where):
    if not isinstance(obj, dict) or key not in obj:
        raise DataError(where + ": нет ключа «" + key + "»")
    val = obj[key]
    if typ is float:
        ok = isinstance(val, (int, float)) and not isinstance(val, bool)
    else:
        ok = isinstance(val, typ) and not (typ is int and isinstance(val, bool))
    if not ok:
        raise DataError(where + "." + key + ": ожидался " + typ.__name__)
    return val


def load_json(path: Path) -> dict:
    if not path.exists():
        raise DataError("нет файла данных: " + str(path))
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise DataError(str(path) + ": битый JSON: " + str(exc)) from exc


def load_data(data_dir: Optional[Path] = None) -> dict:
    root = Path(data_dir) if data_dir else DATA_DIR
    data = load_json(root / "gorod_mvp.json")
    data["press"] = load_json(root / "press.json")
    validate(data)
    return data


def validate(data: dict) -> None:
    if _need(data, "schema_version", int, "gorod_mvp") != SCHEMA_VERSION:
        raise DataError("gorod_mvp.schema_version: ожидалась версия " + str(SCHEMA_VERSION))
    meta = _need(data, "meta", dict, "gorod_mvp")
    for k in ("election_week", "election_period_weeks", "actions_per_week", "start_money",
              "start_awareness", "skill_pool", "skill_divisor", "crit_margin", "fumble_roll"):
        _need(meta, k, int, "meta")
    eco = _need(data, "economy", dict, "gorod_mvp")
    for k in ("income_base", "income_per_support"):
        _need(eco, k, float, "economy")
    tun = _need(data, "tuning", dict, "gorod_mvp")
    for k in ("drift_k", "decay", "flip_trust_penalty", "repeat_divisor", "align_k",
              "broken_mistrust_mult", "trust_vote_base", "turnout_noise"):
        _need(tun, k, float, "tuning")
    skills = _need(data, "skills", dict, "gorod_mvp")
    groups = _need(data, "groups", dict, "gorod_mvp")
    props = _need(data, "proposals", dict, "gorod_mvp")
    papers = _need(data, "papers", dict, "gorod_mvp")
    if not groups or not props or not papers:
        raise DataError("gorod_mvp: группы, вопросы и газеты не могут быть пустыми")
    for gid, g in groups.items():
        w = "groups." + gid
        _need(g, "size", int, w)
        _need(g, "turnout", float, w)
        st = _need(g, "start", dict, w)
        for k in ("support_player", "support_rival", "trust"):
            _need(st, k, float, w + ".start")
        sal = _need(g, "salience", dict, w)
        for pid in props:
            _need(sal, pid, float, w + ".salience")
        forms = _need(g, "forms", dict, w)
        for case in ("im", "rod", "dat", "vin", "tv", "pr"):
            _need(forms, case, str, w + ".forms")
        _need(g, "aliases", list, w)
        voices = _need(g, "voices", dict, w)
        for k in ("pleased", "angry"):
            if not _need(voices, k, list, w + ".voices"):
                raise DataError(w + ".voices." + k + ": пустой список")
    for pid, p in props.items():
        w = "proposals." + pid
        _need(p, "council_difficulty", int, w)
        stance = _need(p, "stance", dict, w)
        for gid in groups:
            val = _need(stance, gid, float, w + ".stance")
            if not -1.0 <= val <= 1.0:
                raise DataError(w + ".stance." + gid + ": вне диапазона [-1, 1]")
        forms = _need(p, "forms", dict, w)
        for case in ("im", "rod", "dat", "vin"):
            _need(forms, case, str, w + ".forms")
        _need(p, "aliases", list, w)
    for pid, p in papers.items():
        w = "papers." + pid
        _need(p, "reach", int, w)
        _need(p, "bias_player", float, w)
        _need(p, "bias_rival", float, w)
        forms = _need(p, "forms", dict, w)
        for case in ("im", "dat", "pr"):
            _need(forms, case, str, w + ".forms")
        _need(p, "aliases", list, w)
    actions = _need(data, "actions", dict, "gorod_mvp")
    for aid in ("meeting", "statement", "promise", "initiative", "interview"):
        a = _need(actions, aid, dict, "actions")
        w = "actions." + aid
        _need(a, "name", str, w)
        if _need(a, "skill", str, w) not in skills:
            raise DataError(w + ".skill: неизвестный навык")
        _need(a, "difficulty", int, w)
        _need(a, "cost", int, w)
        for slot in _need(a, "requires", list, w):
            if slot not in SLOTS:
                raise DataError(w + ".requires: неизвестный слот " + str(slot))
    for k in ("base", "fail"):
        _need(actions["meeting"], k, float, "actions.meeting")
    _need(actions["statement"], "base", float, "actions.statement")
    for k in ("base", "default_deadline", "max_deadline"):
        _need(actions["promise"], k, float if k == "base" else int, "actions.promise")
    _need(actions["initiative"], "base", float, "actions.initiative")
    for k in ("awareness_gain", "gaffe_trust"):
        _need(actions["interview"], k, float, "actions.interview")
    prio = _need(data, "action_priority", list, "gorod_mvp")
    if sorted(prio) != sorted(actions):
        raise DataError("action_priority: должен перечислять все действия ровно один раз")
    om = _need(data, "outcome_mult", dict, "gorod_mvp")
    for k in ("crit", "success", "fail"):
        _need(om, k, float, "outcome_mult")
    pr = _need(data, "promise_rules", dict, "gorod_mvp")
    for k in ("kept_trust", "kept_support", "broken_trust", "broken_support"):
        _need(pr, k, float, "promise_rules")
    rv = _need(data, "rival", dict, "gorod_mvp")
    for k in ("im", "rod", "dat", "vin", "tv"):
        _need(_need(rv, "forms", dict, "rival"), k, str, "rival.forms")
    _need(rv, "title", str, "rival")
    pos = _need(rv, "positions", dict, "rival")
    for pid in props:
        if _need(pos, pid, int, "rival.positions") not in (-1, 0, 1):
            raise DataError("rival.positions." + pid + ": допустимо -1, 0, 1")
    for k in ("meeting_gain", "attack_trust", "attack_support", "attack_chance"):
        _need(rv, k, float, "rival")
    _need(rv, "attack_memory_weeks", int, "rival")
    npcs = _need(data, "npcs", dict, "gorod_mvp")
    sp = _need(npcs, "speaker", dict, "npcs")
    for k in ("loyalty", "gain_on_success"):
        _need(sp, k, int, "npcs.speaker")
    _need(sp, "per_loyalty_point", float, "npcs.speaker")
    _need(sp, "name", str, "npcs.speaker")
    ed = _need(npcs, "editor", dict, "npcs")
    _need(ed, "loyalty", int, "npcs.editor")
    if _need(ed, "paper", str, "npcs.editor") not in papers:
        raise DataError("npcs.editor.paper: нет такой газеты")
    lex = _need(data, "lexicon", dict, "gorod_mvp")
    la = _need(lex, "actions", dict, "lexicon")
    for aid in actions:
        _need(la, aid, list, "lexicon.actions")
    for k in ("negative", "negatable", "positive", "month_words"):
        _need(lex, k, list, "lexicon")
    _need(lex, "numbers", dict, "lexicon")
    sides = _need(data, "sides", dict, "gorod_mvp")
    for s in ("1", "-1"):
        for k in ("name", "pos", "goal"):
            _need(_need(sides, s, dict, "sides"), k, str, "sides." + s)
    press = _need(data, "press", dict, "gorod_mvp")
    if _need(press, "schema_version", int, "press") != SCHEMA_VERSION:
        raise DataError("press.schema_version: ожидалась версия " + str(SCHEMA_VERSION))
    kinds = _need(press, "kinds", dict, "press")
    for kind in FACT_KINDS:
        items = _need(kinds, kind, list, "press.kinds")
        angles = set()
        for t in items:
            for k in ("id", "angle", "headline", "lead"):
                _need(t, k, str, "press.kinds." + kind)
            angles.add(t["angle"])
        if angles != {"pro", "contra", "neutral"}:
            raise DataError("press.kinds." + kind + ": нужны шаблоны с углами pro, contra, neutral")
    for k in ("decision_words", "result_words"):
        _need(press, k, dict, "press")
    gender = _need(press, "gender", dict, "press")
    keys = None
    for gk, forms in gender.items():
        if not isinstance(forms, dict) or not forms:
            raise DataError("press.gender." + gk + ": ожидался непустой словарь")
        if keys is not None and set(forms) != keys:
            raise DataError("press.gender." + gk + ": набор слов не совпадает с другими родами")
        keys = set(forms)


FACT_KINDS = ("meeting_ok", "meeting_fail", "statement", "statement_weak", "flip_flop", "promise",
              "promise_kept", "promise_broken", "initiative_ok", "initiative_fail", "interview_ok",
              "interview_gaffe", "rival_meeting", "rival_attack", "election")


# ================= состояние =================
@dataclass
class Card:
    action: str
    group: str = ""
    proposal: str = ""
    side: int = 0
    paper: str = ""
    deadline: int = 0
    text: str = ""


@dataclass
class GroupState:
    support_player: float
    support_rival: float
    trust: float


@dataclass
class Promise:
    id: str
    proposal: str
    side: int
    made_week: int
    deadline_week: int
    groups: List[str]
    status: str = "open"  # open | kept | broken


@dataclass
class Fact:
    id: str
    week: int
    kind: str
    actor: str  # player | rival | city
    outcome: int  # +1 хорошо для актора, -1 плохо, 0 нейтрально
    magnitude: float
    proposal: str = ""
    side: int = 0
    group: str = ""
    paper: str = ""
    extra: Dict[str, object] = field(default_factory=dict)
    deltas: Dict[str, float] = field(default_factory=dict)


@dataclass
class State:
    schema_version: int
    player_name: str
    gender: str
    skills: Dict[str, int]
    week: int
    money: int
    actions_left: int
    awareness: float
    groups: Dict[str, GroupState]
    positions: Dict[str, int]
    rival_positions: Dict[str, int]
    policies: Dict[str, int]
    promises: List[Promise]
    facts: List[Fact]
    npc_loyalty: Dict[str, int]
    said: Dict[str, int]
    press_used: Dict[str, int]
    week_seeds: List[int]
    next_election_week: int
    role: str = "кандидат"
    elections: List[dict] = field(default_factory=list)
    week_cards: List[dict] = field(default_factory=list)
    determinism_policy: str = "F"


def _entropy_seed() -> int:
    return random.SystemRandom().randrange(1, 2 ** 31 - 1)


def week_rng(state: State, offset: int) -> random.Random:
    if not state.week_seeds:
        raise RuleError("нет зерна недели (схема F)")
    return random.Random(state.week_seeds[-1] * 1000 + offset)


def new_game(data: dict, player_name: str, skills: Dict[str, int], gender: str,
             seed: Optional[int] = None) -> State:
    meta = data["meta"]
    if gender not in data["press"]["gender"]:
        raise RuleError("пол кандидата: " + ", ".join(sorted(data["press"]["gender"])))
    name = (player_name or "").strip()
    if not name:
        raise RuleError("имя кандидата не может быть пустым")
    if set(skills) != set(data["skills"]):
        raise RuleError("навыки: нужны ровно " + ", ".join(data["skills"]))
    if any(isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 100 for v in skills.values()) or sum(skills.values()) != meta["skill_pool"]:
        raise RuleError("навыки: целые 0..100, в сумме " + str(meta["skill_pool"]))
    groups = {gid: GroupState(float(g["start"]["support_player"]), float(g["start"]["support_rival"]),
                              float(g["start"]["trust"])) for gid, g in data["groups"].items()}
    return State(
        schema_version=SCHEMA_VERSION, player_name=name, gender=gender, skills=dict(skills), week=1,
        money=meta["start_money"], actions_left=meta["actions_per_week"],
        awareness=float(meta["start_awareness"]), groups=groups,
        positions={pid: 0 for pid in data["proposals"]},
        rival_positions=dict(data["rival"]["positions"]),
        policies={pid: 0 for pid in data["proposals"]}, promises=[], facts=[],
        npc_loyalty={nid: int(n["loyalty"]) for nid, n in data["npcs"].items()},
        said={}, press_used={}, week_seeds=[seed if seed is not None else _entropy_seed()],
        next_election_week=meta["election_week"])


def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


# ================= вспомогательное =================
def sal(data: dict, gid: str, pid: str) -> float:
    return float(data["groups"][gid]["salience"][pid]) / 100.0


def stance(data: dict, gid: str, pid: str) -> float:
    return float(data["proposals"][pid]["stance"][gid])


def _fact(state: State, kind: str, actor: str, outcome: int, magnitude: float, **kw) -> Fact:
    f = Fact(id="f" + str(state.week) + "_" + str(len(state.facts)), week=state.week, kind=kind,
             actor=actor, outcome=outcome, magnitude=round(magnitude, 2), **kw)
    state.facts.append(f)
    return f


def _apply(state: State, fact: Fact, gid: str, support: float = 0.0, trust: float = 0.0, rival: float = 0.0) -> None:
    g = state.groups[gid]
    if support:
        old = g.support_player
        g.support_player = clamp(g.support_player + support)
        fact.deltas[gid + ".support"] = round(fact.deltas.get(gid + ".support", 0.0) + g.support_player - old, 2)
    if trust:
        old = g.trust
        g.trust = clamp(g.trust + trust)
        fact.deltas[gid + ".trust"] = round(fact.deltas.get(gid + ".trust", 0.0) + g.trust - old, 2)
    if rival:
        old = g.support_rival
        g.support_rival = clamp(g.support_rival + rival)
        fact.deltas[gid + ".rival"] = round(fact.deltas.get(gid + ".rival", 0.0) + g.support_rival - old, 2)


def broken_with(state: State, gid: str) -> int:
    return sum(1 for p in state.promises if p.status == "broken" and gid in p.groups)


def _mistrust(state: State, data: dict, gid: str) -> float:
    """Множитель «город помнит»: каждое сорванное обещание этой группе ослабляет слова кандидата."""
    k = float(data["tuning"]["broken_mistrust_mult"])
    return k ** broken_with(state, gid)


# ================= предпросмотр и бросок =================
def missing_slots(data: dict, card: Card) -> List[str]:
    if card.action not in data["actions"]:
        raise RuleError("неизвестное действие: " + card.action)
    out = []
    for slot in data["actions"][card.action]["requires"]:
        if not getattr(card, slot):
            out.append(slot)
    if card.proposal and card.action in ("statement", "promise", "initiative") and card.side not in (-1, 1):
        out.append("side")
    return out


def difficulty(state: State, data: dict, card: Card) -> int:
    a = data["actions"][card.action]
    diff = int(a["difficulty"])
    if card.action == "initiative" and card.proposal:
        sp = data["npcs"]["speaker"]
        diff += int(data["proposals"][card.proposal]["council_difficulty"])
        diff -= int(round((state.npc_loyalty["speaker"] - 50) * float(sp["per_loyalty_point"])))
    if card.action == "meeting" and card.group:
        diff += 5 * broken_with(state, card.group)
    return diff


def modifier(state: State, data: dict, card: Card) -> int:
    skill = data["actions"][card.action]["skill"]
    return state.skills[skill] // data["meta"]["skill_divisor"]


def chance(state: State, data: dict, card: Card) -> int:
    need = difficulty(state, data, card) - modifier(state, data, card)
    return int(clamp(101 - need, 1, 99))


def preview(state: State, data: dict, card: Card) -> dict:
    a = data["actions"][card.action]
    miss = missing_slots(data, card)
    return {"action": a["name"], "chance": chance(state, data, card) if not miss else None,
            "cost": a["cost"], "missing": miss, "summary": describe_card(data, card),
            "warnings": warnings(state, data, card)}


def warnings(state: State, data: dict, card: Card) -> List[str]:
    out = []
    if card.proposal and card.side in (-1, 1) and card.action in ("statement", "promise", "initiative", "interview"):
        if state.positions.get(card.proposal, 0) == -card.side:
            out.append("смена позиции: все группы снизят доверие")
        n = state.said.get(card.proposal + ":" + str(card.side), 0)
        if n and card.action in ("statement", "interview", "promise"):
            out.append("город это уже слышал (" + str(n) + " раз): эффект слабее")
        for p in state.promises:
            if p.status == "open" and p.proposal == card.proposal and p.side == -card.side:
                out.append("противоречит открытому обещанию — оно будет сорвано")
    if card.action == "initiative" and card.proposal and state.policies.get(card.proposal) == card.side and card.side:
        out.append("такое решение уже принято")
    a = data["actions"][card.action]
    if state.money < a["cost"]:
        out.append("не хватает денег")
    return out


def describe_card(data: dict, card: Card) -> str:
    parts = [data["actions"][card.action]["name"]]
    if card.group:
        parts.append("группа: " + data["groups"][card.group]["forms"]["im"])
    if card.paper:
        parts.append("газета: " + data["papers"][card.paper]["forms"]["im"])
    if card.proposal:
        parts.append("вопрос: " + data["proposals"][card.proposal]["forms"]["im"])
        if card.side in (-1, 1):
            parts.append("позиция: " + data["sides"][str(card.side)]["name"])
    if card.action == "promise":
        parts.append("срок: " + str(card.deadline or data["actions"]["promise"]["default_deadline"]) + " нед.")
    return " · ".join(parts)


def _roll(state: State, data: dict, card: Card) -> dict:
    rng = week_rng(state, 10 + len(state.week_cards))
    r = rng.randint(1, 100)
    total = r + modifier(state, data, card)
    diff = difficulty(state, data, card)
    if r <= data["meta"]["fumble_roll"]:
        tier = "fail"
    elif total >= diff + data["meta"]["crit_margin"]:
        tier = "crit"
    elif total >= diff:
        tier = "success"
    else:
        tier = "fail"
    return {"roll": r, "total": total, "difficulty": diff, "tier": tier, "rng": rng}


# ================= действия =================
def perform(state: State, data: dict, card: Card) -> dict:
    """Выполнить карточку. Возвращает {'roll':..., 'tier':..., 'facts': [Fact]}."""
    if state.actions_left <= 0:
        raise RuleError("на этой неделе действия закончились")
    miss = missing_slots(data, card)
    if miss:
        raise RuleError("не заполнены слоты: " + ", ".join(miss))
    for slot, table in (("group", "groups"), ("proposal", "proposals"), ("paper", "papers")):
        val = getattr(card, slot)
        if val and val not in data[table]:
            raise RuleError("неизвестное значение слота " + slot + ": " + val)
    a = data["actions"][card.action]
    if state.money < a["cost"]:
        raise RuleError("не хватает денег: нужно " + str(a["cost"]))
    if card.action == "initiative" and state.policies.get(card.proposal) == card.side:
        raise RuleError("такое решение уже принято")
    if card.action == "promise":
        dl = card.deadline or int(a["default_deadline"])
        if not 1 <= dl <= int(a["max_deadline"]):
            raise RuleError("срок обещания: от 1 до " + str(a["max_deadline"]) + " недель")
        card.deadline = dl
        for p in state.promises:
            if p.status == "open" and p.proposal == card.proposal and p.side == card.side:
                raise RuleError("такое обещание уже дано (срок — неделя " + str(p.deadline_week) + ")")
        if state.policies.get(card.proposal) == card.side:
            raise RuleError("это уже сделано: обещать нечего")
    roll = _roll(state, data, card)
    n_before = len(state.facts)
    state.money -= a["cost"]
    state.actions_left -= 1
    mult = float(data["outcome_mult"][roll["tier"]])
    HANDLERS[card.action](state, data, card, roll, mult)
    state.week_cards.append({"card": asdict(card), "roll": roll["roll"], "tier": roll["tier"]})
    return {"roll": roll["roll"], "total": roll["total"], "difficulty": roll["difficulty"],
            "tier": roll["tier"], "facts": state.facts[n_before:]}


def _position_change(state: State, data: dict, pid: str, side: int) -> Optional[Fact]:
    """Публичная позиция. Разворот — штраф доверия у всех и факт flip_flop; противоречащие обещания срываются."""
    prev = state.positions.get(pid, 0)
    state.positions[pid] = side
    fact = None
    if prev == -side:
        pen = float(data["tuning"]["flip_trust_penalty"])
        fact = _fact(state, "flip_flop", "player", -1, pen, proposal=pid, side=side)
        for gid in state.groups:
            _apply(state, fact, gid, trust=-pen)
    for p in state.promises:
        if p.status == "open" and p.proposal == pid and p.side == -side:
            _break_promise(state, data, p)
    return fact


def _broadcast(state: State, data: dict, fact: Fact, pid: str, side: int, base: float, scale: float) -> None:
    for gid in state.groups:
        d = base * stance(data, gid, pid) * side * sal(data, gid, pid) * scale
        if d > 0:
            d *= _mistrust(state, data, gid)
        _apply(state, fact, gid, support=d)


def _repeat_factor(state: State, data: dict, pid: str, side: int) -> float:
    key = pid + ":" + str(side)
    n = state.said.get(key, 0)
    state.said[key] = n + 1
    return 1.0 / (1.0 + float(data["tuning"]["repeat_divisor"]) * n)


def _do_statement(state, data, card, roll, mult, kind_ok="statement", base_key="statement", extra_scale=1.0):
    rep = _repeat_factor(state, data, card.proposal, card.side)
    _position_change(state, data, card.proposal, card.side)
    reach = 0.5 + state.awareness / 100.0
    base = float(data["actions"][base_key]["base"])
    kind = kind_ok if rep == 1.0 else "statement_weak"
    outcome = 1 if roll["tier"] != "fail" else 0
    fact = _fact(state, kind, "player", outcome, base * mult * rep * extra_scale, proposal=card.proposal,
                 side=card.side, paper=card.paper)
    _broadcast(state, data, fact, card.proposal, card.side, base, reach * mult * rep * extra_scale)
    return fact


def _do_promise(state, data, card, roll, mult):
    fact = _do_statement(state, data, card, roll, mult, kind_ok="promise", base_key="promise")
    pleased = [gid for gid in state.groups if stance(data, gid, card.proposal) * card.side > 0]
    pr = Promise(id="p" + str(len(state.promises) + 1), proposal=card.proposal, side=card.side,
                 made_week=state.week, deadline_week=state.week + card.deadline - 1, groups=pleased)
    state.promises.append(pr)
    fact.extra.update({"deadline": card.deadline, "promise_id": pr.id})
    if fact.kind == "statement_weak":
        fact.kind = "promise"


def _do_interview(state, data, card, roll, mult):
    a = data["actions"]["interview"]
    paper = data["papers"][card.paper]
    if roll["tier"] == "fail":
        fact = _fact(state, "interview_gaffe", "player", -1, abs(float(a["gaffe_trust"])), paper=card.paper,
                     proposal=card.proposal, side=card.side)
        for gid in state.groups:
            _apply(state, fact, gid, trust=float(a["gaffe_trust"]))
        state.awareness = clamp(state.awareness + float(a["awareness_gain"]) * 0.5)
        return
    gain = float(a["awareness_gain"]) * paper["reach"] / 50.0 * mult
    state.awareness = clamp(state.awareness + gain)
    if paper.get("editor"):
        state.npc_loyalty[paper["editor"]] = int(clamp(state.npc_loyalty[paper["editor"]] + 2))
    if card.proposal and card.side in (-1, 1):
        fact = _do_statement(state, data, card, roll, mult, kind_ok="interview_ok", base_key="statement",
                             extra_scale=paper["reach"] / 50.0)
        if fact.kind == "statement_weak":
            fact.kind = "interview_ok"
    else:
        fact = _fact(state, "interview_ok", "player", 1, gain, paper=card.paper)
    fact.extra["awareness_gain"] = round(gain, 2)


def _do_meeting(state, data, card, roll, mult):
    a = data["actions"]["meeting"]
    gid = card.group
    if roll["tier"] == "fail":
        fact = _fact(state, "meeting_fail", "player", -1, abs(float(a["fail"])), group=gid)
        _apply(state, fact, gid, support=float(a["fail"]))
        return
    align = sum(stance(data, gid, pid) * pos * sal(data, gid, pid)
                for pid, pos in state.positions.items() if pos)
    d = (float(a["base"]) + float(data["tuning"]["align_k"]) * align) * mult * _mistrust(state, data, gid)
    fact = _fact(state, "meeting_ok", "player", 1 if d >= 0 else -1, abs(d), group=gid,
                 extra={"align": round(align, 2)})
    _apply(state, fact, gid, support=d, trust=1.0 * mult)


def _do_initiative(state, data, card, roll, mult):
    pid, side = card.proposal, card.side
    if roll["tier"] == "fail":
        fact = _fact(state, "initiative_fail", "player", -1, 3.0, proposal=pid, side=side)
        for gid in state.groups:
            if stance(data, gid, pid) * side > 0:
                _apply(state, fact, gid, support=-2.0)
        return
    state.policies[pid] = side
    _position_change(state, data, pid, side)
    base = float(data["actions"]["initiative"]["base"])
    fact = _fact(state, "initiative_ok", "player", 1, base * mult, proposal=pid, side=side)
    for gid in state.groups:
        _apply(state, fact, gid, support=base * stance(data, gid, pid) * side * sal(data, gid, pid) * mult)
    sp = data["npcs"]["speaker"]
    state.npc_loyalty["speaker"] = int(clamp(state.npc_loyalty["speaker"] + int(sp["gain_on_success"])))
    for p in state.promises:
        if p.status == "open" and p.proposal == pid and p.side == side:
            _keep_promise(state, data, p)


HANDLERS = {"statement": _do_statement, "promise": _do_promise, "interview": _do_interview,
            "meeting": _do_meeting, "initiative": _do_initiative}


def _keep_promise(state: State, data: dict, p: Promise) -> None:
    p.status = "kept"
    r = data["promise_rules"]
    fact = _fact(state, "promise_kept", "player", 1, float(r["kept_trust"]), proposal=p.proposal, side=p.side,
                 extra={"promise_id": p.id, "made_week": p.made_week})
    for gid in p.groups:
        _apply(state, fact, gid, support=float(r["kept_support"]) * sal(data, gid, p.proposal),
               trust=float(r["kept_trust"]))


def _break_promise(state: State, data: dict, p: Promise) -> None:
    p.status = "broken"
    r = data["promise_rules"]
    fact = _fact(state, "promise_broken", "player", -1, abs(float(r["broken_trust"])), proposal=p.proposal,
                 side=p.side, extra={"promise_id": p.id, "made_week": p.made_week})
    for gid in p.groups:
        _apply(state, fact, gid, support=float(r["broken_support"]) * sal(data, gid, p.proposal),
               trust=float(r["broken_trust"]))


# ================= ход мира =================
def _rival_turn(state: State, data: dict, rng: random.Random) -> None:
    rv = data["rival"]
    since = state.week - int(rv["attack_memory_weeks"])
    sins = [f for f in state.facts if f.actor == "player" and f.week > since
            and f.kind in ("promise_broken", "flip_flop") and not f.extra.get("attacked")]
    if sins and rng.random() < float(rv["attack_chance"]):
        sin = max(sins, key=lambda f: (f.magnitude, f.id))
        sin.extra["attacked"] = True
        fact = _fact(state, "rival_attack", "rival", 1, abs(float(rv["attack_trust"])), proposal=sin.proposal,
                     side=sin.side, extra={"about": sin.id})
        targets = [gid for gid in state.groups if sin.kind == "flip_flop"
                   or gid in next((p.groups for p in state.promises if p.id == sin.extra.get("promise_id")), [])]
        for gid in targets:
            _apply(state, fact, gid, support=float(rv["attack_support"]), trust=float(rv["attack_trust"]))
        return
    # иначе — встреча там, где кандидат собирает больше всего голосов
    def threat(g: str) -> tuple:
        gs, gd = state.groups[g], data["groups"][g]
        total = gs.support_player + gs.support_rival
        return (gd["size"] * gd["turnout"] * (gs.support_player / total if total else 0.5), g)
    gid = max(state.groups, key=threat)
    fact = _fact(state, "rival_meeting", "rival", 1, float(rv["meeting_gain"]), group=gid)
    _apply(state, fact, gid, rival=float(rv["meeting_gain"]))


def _drift(state: State, data: dict) -> None:
    """Группы тянутся к тем, чьи позиции совпадают с их интересами; без работы поддержка остывает."""
    t = data["tuning"]
    for gid, g in state.groups.items():
        st = data["groups"][gid]["start"]
        ap = sum(stance(data, gid, pid) * pos * sal(data, gid, pid) for pid, pos in state.positions.items())
        ar = sum(stance(data, gid, pid) * pos * sal(data, gid, pid) for pid, pos in state.rival_positions.items())
        pol = sum(stance(data, gid, pid) * pos * sal(data, gid, pid) for pid, pos in state.policies.items())
        g.support_player = clamp(g.support_player + float(t["drift_k"]) * ap * (g.trust / 50.0))
        g.support_rival = clamp(g.support_rival + float(t["drift_k"]) * ar)
        g.support_player = clamp(g.support_player + (float(st["support_player"]) - g.support_player) * float(t["decay"]))
        g.support_rival = clamp(g.support_rival + (float(st["support_rival"]) - g.support_rival) * float(t["decay"]))
        if pol:
            g.support_player = clamp(g.support_player + 0.5 * pol)


def election(state: State, data: dict, rng: random.Random) -> dict:
    tv = float(data["tuning"]["trust_vote_base"])
    noise = float(data["tuning"]["turnout_noise"])
    rows, pv, rv = [], 0.0, 0.0
    for gid in sorted(state.groups):
        g, gd = state.groups[gid], data["groups"][gid]
        turnout = clamp(float(gd["turnout"]) + rng.uniform(-noise, noise), 0.0, 1.0)
        voters = gd["size"] * turnout
        ep = g.support_player * (tv + g.trust / 100.0)
        er = g.support_rival
        share = ep / (ep + er) if ep + er > 0 else 0.5
        rows.append({"group": gid, "voters": int(round(voters)), "share_player": round(share, 3),
                     "player": int(round(voters * share)), "rival": int(round(voters * (1 - share)))})
        pv += voters * share
        rv += voters * (1 - share)
    return {"week": state.week, "player": int(round(pv)), "rival": int(round(rv)), "won": pv > rv, "rows": rows}


def end_week(state: State, data: dict) -> dict:
    """Ход мира: соперник, сроки обещаний, дрейф, деньги, газеты, выборы. Затем новая неделя."""
    from . import press  # локальный импорт: press зависит от engine
    rng = week_rng(state, 1000)
    start = len(state.facts)
    _rival_turn(state, data, rng)
    for p in state.promises:
        if p.status == "open" and p.deadline_week <= state.week:
            _break_promise(state, data, p)
    _drift(state, data)
    avg = sum(g.support_player for g in state.groups.values()) / len(state.groups)
    income = int(round(float(data["economy"]["income_base"]) + float(data["economy"]["income_per_support"]) * avg))
    state.money += income
    result = None
    if state.week >= state.next_election_week:
        result = election(state, data, rng)
        state.elections.append(result)
        state.role = "мэр" if result["won"] else "кандидат"
        _fact(state, "election", "player", 1 if result["won"] else -1, 20.0,
              extra={"pv": result["player"], "rv": result["rival"], "won": result["won"]})
        state.next_election_week = state.week + int(data["meta"]["election_period_weeks"])
    week_facts = [f for f in state.facts if f.week == state.week]
    articles = press.write_week(state, data, week_facts, rng)
    report = {"week": state.week, "income": income, "world_facts": state.facts[start:], "articles": articles,
              "election": result}
    state.week += 1
    state.actions_left = data["meta"]["actions_per_week"]
    state.week_cards = []
    state.week_seeds.append(_entropy_seed() if state.determinism_policy == "F" else 0)
    del state.week_seeds[:-200]
    return report


# ================= сохранения =================
def to_dict(state: State) -> dict:
    return asdict(state)


def from_dict(d: dict) -> State:
    if d.get("schema_version") != SCHEMA_VERSION:
        raise DataError("сохранение: неподдерживаемая версия схемы " + str(d.get("schema_version")))
    try:
        d = dict(d)
        d["groups"] = {k: GroupState(**v) for k, v in d["groups"].items()}
        d["promises"] = [Promise(**p) for p in d["promises"]]
        d["facts"] = [Fact(**f) for f in d["facts"]]
        return State(**d)
    except (KeyError, TypeError) as exc:
        raise DataError("сохранение повреждено: " + str(exc)) from exc


def save_game(state: State, path: Path) -> None:
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(to_dict(state), ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def load_game(path: Path) -> State:
    return from_dict(load_json(Path(path)))
