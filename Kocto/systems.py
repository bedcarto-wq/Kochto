from __future__ import annotations

import json
import random
import re
import string as _string
from dataclasses import replace as _replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from models import (ActionData, DataError, ElectoralSystem, GameData, GameState,
                    GroupRuntime, PartyRuntime, PrisonStatus, Role, WeekFact,
                    WEEKLY_ACTION_LIMIT, SIMILARITY_THRESHOLD, SIMILARITY_WINDOW_WEEKS,
                    append_jsonl, load_json, save_json,
                    user_data_path, NN_EVAL_AB, NN_EVAL_AB_SUMMARY, NN_EVAL_ANALYZER,
                    NN_EVAL_PARSER_DEBUG)

# ================= имена полей JSON (контракт схемы, НЕ контент) =================
K_ACTIONS = "actions"
K_ACTION_ID = "id"
K_TITLE = "title"
K_DESC = "description"
K_INTENT = "intent"
K_ISSUE = "issue"
K_TARGET_GROUP = "target_group"
K_TARGET_CAND = "target_candidate"
K_DELAYED = "delayed"
K_COST = "cost"
K_SKILL = "skill"
K_DIFFICULTY = "difficulty"
K_EFFECTS = "effects"
K_SECRET = "secret"
K_ILLEGALITY = "illegality"
K_RISK = "risk"
K_CATEGORY = "category"

K_BAL_DEFAULT_SKILL = "default_skill"
K_BAL_DEFAULT_DIFF = "default_difficulty"
K_BAL_ARRESTED_ALLOWED = "arrested_allowed_intents"
K_BAL_INVESTIGATION_MAX = "investigation_max"
K_BAL_WEEKLY_INCOME = "weekly_income"
K_BAL_SEAT_INCOME = "seat_income"
K_BAL_WEEKLY_EXPENSES = "weekly_expenses"
K_BAL_PROMISE_UPKEEP = "promise_upkeep"

K_AN_TIER_PRIOR = "tier_distribution_prior"
K_AN_TIER_EFFECTS = "tier_effects"
K_AN_TIER_MARGINS = "tier_margins"
K_AN_CTX_WEIGHTS = "context_weights"
K_AN_REACTION_TABLES = "reaction_tables"
K_AN_SECONDARY_CHANCE = "secondary_chance"
K_AN_DRIFT_BOUND = "drift_bound"
K_AN_PLAUS_BASE = "plausibility_base"

K_TPL_HEADLINES = "headlines"
K_TPL_BODIES = "bodies"
K_TPL_OPENERS = "openers"
K_TPL_CLOSERS = "closers"
K_TPL_EVAL = "eval_words"
K_TPL_EVENT = "event_words"
K_TPL_CONSEQ = "consequences"
K_TPL_SOURCE = "sources"
K_TPL_INTROS = "intros"
K_TPL_QUOTES = "quotes"
K_TPL_CONNECTORS = "connectors"
K_TPL_SYSMSG = "system_messages"
K_TPL_EFFPHRASE = "effect_phrases"
K_TPL_ISSUE_NAMES = "issue_names"          # id темы -> русское название (необязательно)
K_TPL_SLOT_FALLBACKS = "slot_fallbacks"    # чем заполнить пустой слот текста (необязательно)

K_EFF_TYPE = "type"
K_EFF_GROUP = "group"
K_EFF_STAT = "stat"
K_EFF_DELTA = "delta"
K_EFF_SUBJECT = "subject"
K_EFF_KIND = "kind"

# enum-константы исходов (структура механики: знаки, не балансные числа и не слова)
TIERS = ["great", "solid", "complication", "minor", "major", "catastrophe"]
TIER_SIGN = {"great": 1, "solid": 1, "complication": 0, "minor": -1, "major": -1, "catastrophe": -1}
# множество имён навыков игрока (контракт схемы, не контент)
SKILL_FIELDS = {"charisma", "persuasion", "organization", "media", "administration",
                "stealth", "connections", "security"}

DATA: Optional[GameData] = None
DATA_DIR: Optional[Path] = None
ACTIONS: Dict[str, ActionData] = {}
_PENDING_REVIEW: List[Dict[str, Any]] = []
_FORMATTER = _string.Formatter()
_DEBUG_PARSER = False


def set_debug_parser(flag: bool) -> None:
    global _DEBUG_PARSER
    _DEBUG_PARSER = bool(flag)


# ================= init / rng (схема F; уход от детерминизма — после рецензий) =================
def init_data(data: GameData, data_dir: Optional[Path] = None) -> None:
    global DATA, DATA_DIR
    DATA = data
    DATA_DIR = Path(data_dir) if data_dir else user_data_path()
    refresh_actions()


def _entropy_seed() -> int:
    return random.SystemRandom().randrange(1, 2 ** 31 - 1)


def draw_next_week_seed(state: GameState) -> int:
    seed = _entropy_seed()
    state.week_seeds.append(seed)
    while len(state.week_seeds) > 200:
        state.week_seeds.pop(0)
    return seed


def get_week_rng(state: GameState, offset: int = 0) -> random.Random:
    if state.determinism_policy == "F":
        if not state.week_seeds:
            draw_next_week_seed(state)
        return random.Random(state.week_seeds[-1] + offset)
    return random.Random()


def calculate_council(state: GameState, electoral_system: ElectoralSystem) -> int:
    councils = (DATA.councils if DATA else {}) or {}
    return int(councils.get("seats", 9))


def rng_state_to_json(rng: random.Random) -> str:
    return json.dumps(rng.getstate())


def rng_from_state(state_str: str, seed: int) -> random.Random:
    rng = random.Random(seed)
    if state_str:
        try:
            raw = json.loads(state_str)
            rng.setstate((raw[0], tuple(raw[1]), raw[2]))
        except Exception:
            rng = random.Random(seed)
    return rng


# ================= журнал / бюджет / утилиты =================
def add_log(state: GameState, text: str) -> None:
    state.event_log.append("[нед " + str(state.week) + "] " + text)
    while len(state.event_log) > 200:
        state.event_log.pop(0)


def _bal(key: str) -> Any:
    bal = (DATA.balance if DATA else {}) or {}
    if key in bal:
        return bal[key]
    raise DataError("balance.json: отсутствует обязательный ключ '" + str(key) +
                    "' (параметр резолвера/бюджета/тюрьмы). Вшитых дефолтов нет — добавь его в JSON.")


def budget_info(state: GameState) -> Dict[str, int]:
    income = int(_bal(K_BAL_WEEKLY_INCOME)) + state.council_seats * int(_bal(K_BAL_SEAT_INCOME))
    expenses = int(_bal(K_BAL_WEEKLY_EXPENSES)) + len(state.promises) * int(_bal(K_BAL_PROMISE_UPKEEP))
    return {"treasury": state.treasury, "income": income, "expenses": expenses, "net": income - expenses}


def roll_d100(rng: random.Random, modifier: int = 0, difficulty: int = 50) -> Tuple[int, int, bool]:
    raw = rng.randint(1, 100)
    total = raw + modifier
    return raw, total, total >= difficulty


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def get_group(state: GameState, group_id: str) -> Optional[GroupRuntime]:
    for g in state.groups:
        if g.id == group_id:
            return g
    return None


def get_party(state: GameState, party_id: str) -> Optional[PartyRuntime]:
    for p in state.parties:
        if p.id == party_id:
            return p
    return None


def get_candidate(state: GameState, cand_id: str):
    for c in state.candidates:
        if c.id == cand_id:
            return c
    return None


def get_publication(state: GameState, pub_id: str):
    for p in state.publications:
        if p.id == pub_id:
            return p
    return state.publications[0] if state.publications else None


def week_slots_left(state: GameState) -> int:
    return max(0, WEEKLY_ACTION_LIMIT - len(state.week_actions))


def get_pending_review() -> List[Dict[str, Any]]:
    return _PENDING_REVIEW


def clear_pending_review() -> None:
    global _PENDING_REVIEW
    _PENDING_REVIEW = []


# ================= B-1: поддержка как абсолют, проценты per-level на лету =================
def support_share(state: GameState, subject_id: str, kind: str) -> float:
    pop = int(getattr(state.village, "population", 0) or 0)
    if pop <= 0:
        return 0.0
    total = 0
    for g in state.groups:
        bucket = g.candidate_support if kind == "candidate" else g.party_support
        total += int(bucket.get(subject_id, 0))
    return round(total / pop * 100.0, 2)


# ================= eval-логи (USER-папка; в сборке отдельно от игры) =================
def _refresh_ab_summary(record: Dict[str, Any]) -> None:
    path = user_data_path(NN_EVAL_AB_SUMMARY)
    summary = load_json(path, {"parser_wins": 0, "nn_wins": 0, "consensus": 0, "refusals": 0, "by_intent": {}})
    chosen = record.get("chosen", "")
    if chosen == "parser":
        summary["parser_wins"] = summary.get("parser_wins", 0) + 1
    elif chosen == "nn":
        summary["nn_wins"] = summary.get("nn_wins", 0) + 1
    intent = (record.get("proposal") or {}).get("intent", "unknown")
    by_intent = summary.setdefault("by_intent", {})
    entry = by_intent.setdefault(intent, {"parser": 0, "nn": 0})
    if chosen in ("parser", "nn"):
        entry[chosen] = entry.get(chosen, 0) + 1
    save_json(path, summary)


def log_ab_judgment(record: Dict[str, Any]) -> None:
    append_jsonl(user_data_path(NN_EVAL_AB), record)
    _refresh_ab_summary(record)


def log_analyzer_judgment(record: Dict[str, Any]) -> None:
    append_jsonl(user_data_path(NN_EVAL_ANALYZER), record)


def log_parser_debug(record: Dict[str, Any]) -> None:
    if _DEBUG_PARSER:
        append_jsonl(user_data_path(NN_EVAL_PARSER_DEBUG), record)


# ================= очередь действий =================
def enqueue_action(state: GameState, action: ActionData, target: str, intent: str, delayed: bool,
                   issue: str = "", meta: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    if state.is_game_over:
        return False, "Игра завершена."
    if week_slots_left(state) <= 0:
        return False, "Нет слотов недели (лимит " + str(WEEKLY_ACTION_LIMIT) + ")."
    meta = dict(meta or {})
    cost = action.cost
    if action.id == _free_id():
        cost = int(_wcfg("free_action").get("base_cost", cost)) + tag_cost(meta.get("tags") or [])
    if cost > state.player.money:
        return False, "Недостаточно денег для постановки действия."
    if cost:
        state.player.money -= cost
    state.week_actions.append({"action_id": action.id, "target": target, "intent": intent,
                               "issue": issue or "", "tags": list(meta.get("tags") or []),
                               "stance": str(meta.get("stance", "") or ""), "offer": str(meta.get("offer", "") or ""),
                               "raw": str(meta.get("raw", "") or ""), "delayed": bool(delayed), "enqueued_week": state.week, "cost_paid": cost})
    state.actions_this_week += 1
    chance = estimate_chance(state, state.week_actions[-1])
    state.week_actions[-1]["chance"] = chance
    return True, ("Принято в план недели (слот " + str(len(state.week_actions)) + "/" + str(WEEKLY_ACTION_LIMIT) +
                  "): шанс ~" + str(chance) + "%, цена " + str(cost) + ".")


# ================= обещания / коалиции / партии / отказ =================
def create_promise(state: GameState, group_id: str, issue: str, text: str, kind: str) -> Dict[str, Any]:
    promise = {"id": "promise_" + str(len(state.promises) + 1), "group_id": group_id, "issue": issue,
               "text": text, "kind": kind, "status": "active", "deadline_week": state.week + 4, "progress": 0}
    state.promises.append(promise)
    add_log(state, "Обещание создано: " + text)
    return promise


def forget_promise(state: GameState, rng: random.Random) -> str:
    active = [p for p in state.promises if p["status"] == "active"]
    if not active:
        return "Активных обещаний нет."
    target = active[-1]
    target["status"] = "forgotten"
    group = get_group(state, target["group_id"])
    if group:
        group.loyalty = clamp(group.loyalty - 10, 0, 100)
        group.mood = clamp(group.mood - 5, 0, 100)
    state.player.trust = clamp(state.player.trust - 5, 0, 100)
    add_log(state, "Обещание забыто: " + str(target["text"]))
    return "Обещание забыто: " + str(target["text"]) + ". Доверие и лояльность снизились."


def _fulfill_promises_for(state: GameState, group_id: str, issue: str) -> None:
    if not group_id:
        return
    for promise in state.promises:
        if promise["status"] == "active" and promise["group_id"] == group_id \
                and (not issue or promise["issue"] == issue):
            promise["status"] = "kept"
            promise["progress"] = 100
            state.player.trust = clamp(state.player.trust + 4, 0, 100)
            add_log(state, "Обещание выполнено: " + str(promise["text"]))


def coalition_with(state: GameState, party_id: str, rng: random.Random) -> str:
    party = get_party(state, party_id)
    if not party:
        return "Партия не найдена."
    diff = int(_bal(K_BAL_DEFAULT_DIFF))
    _, total, ok = roll_d100(rng, modifier=state.player.persuasion, difficulty=diff + 5)
    if ok:
        party.trust_to_player = clamp(party.trust_to_player + 10, 0, 100)
        state.parliament_seats["player"] = state.parliament_seats.get("player", 0) + 1
        state.council_seats += 1
        add_log(state, "Коалиция с " + party.name + " заключена.")
        return "Коалиция с " + party.name + " заключена (бросок " + str(total) + "). Место +1."
    party.trust_to_player = clamp(party.trust_to_player - 5, 0, 100)
    return "Переговоры с " + party.name + " провалены (бросок " + str(total) + ")."


def join_party(state: GameState, party_id: str, rng: random.Random) -> Tuple[bool, str]:
    party = get_party(state, party_id)
    if not party:
        return False, "Партия не найдена."
    if getattr(state.player, "party_id", ""):
        return False, "Ты уже состоишь в партии."
    diff = int(_bal(K_BAL_DEFAULT_DIFF))
    _, total, ok = roll_d100(rng, modifier=state.player.persuasion, difficulty=diff)
    if not ok:
        party.trust_to_player = clamp(party.trust_to_player - 3, 0, 100)
        return False, "Вступление в " + party.name + " отклонено (бросок " + str(total) + ")."
    state.player.party_id = party.id
    state.player.party_role = "member"
    party.trust_to_player = clamp(party.trust_to_player + 8, 0, 100)
    add_log(state, "Игрок вступил в " + party.name + ".")
    return True, "Ты вступил в " + party.name + " (бросок " + str(total) + ")."


def create_party(state: GameState, rng: random.Random, name: str) -> Tuple[bool, str]:
    cost = 40
    if getattr(state.player, "party_id", ""):
        return False, "Ты уже состоишь в партии."
    if state.player.money < cost:
        return False, "Недостаточно денег для регистрации партии."
    if state.player.awareness < 15:
        return False, "Слишком низкая узнаваемость для регистрации партии (нужно 15+)."
    state.player.money -= cost
    pid = "player_party"
    party = PartyRuntime(id=pid, name=name or "Партия игрока", popularity=5, trust_to_player=100,
                         discipline=60, scandal=0, seats=0)
    state.parties.append(party)
    state.parliament_seats[pid] = 0
    state.player.party_id = pid
    state.player.party_role = "leader"
    state.player.founded_party = True
    add_log(state, "Зарегистрирована партия " + party.name + ".")
    return True, "Партия «" + party.name + "» зарегистрирована за " + str(cost) + "."


def apply_refusal(state: GameState) -> str:
    state.player.stress = clamp(state.player.stress + 5, 0, 100)
    add_log(state, "Игрок отказался от давления; стресс вырос.")
    return "Вы отказались от давления. Стресс +5."


# ================= композер fallback: структура из templates.json, слов НЕТ в коде =================
def _template_fields(template: str) -> set:
    fields = set()
    for _, field_name, _, _ in _FORMATTER.parse(template):
        if field_name:
            fields.add(field_name.split('.')[0].split('[')[0].split(':')[0].split('!')[0])
    return fields


def _top_issue(group: Any) -> str:
    issues = getattr(group, "issues", None) or {}
    if not issues:
        return ""
    return max(sorted(issues), key=lambda k: issues[k])


def _issue_name(issue_id: str) -> str:
    names = ((DATA.templates if DATA else {}) or {}).get(K_TPL_ISSUE_NAMES) or {}
    return str(names.get(issue_id, issue_id))


def _fill_empty_slots(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Пустые слоты дают «вокруг .» и «Игрок и » — заполняем их из templates.json."""
    out = dict(payload)
    if out.get("issue"):
        out["issue"] = _issue_name(str(out["issue"]))
    fallbacks = ((DATA.templates if DATA else {}) or {}).get(K_TPL_SLOT_FALLBACKS) or {}
    for key, value in fallbacks.items():
        if not str(out.get(key, "") or "").strip():
            out[key] = value
    return out


_RE_SPACES = re.compile(r"\s+")
_RE_SPACE_PUNCT = re.compile(r"\s+([.,:;!?»])")
_RE_EMPTY_SLOT = re.compile(r"(^|[\s«(])[.,:;—-]\s*[.,:;]|[:—]\s*[.,;]|«\s*»|\(\s*\)|\s[и—]\s*$|:\s*$")


def _polish_sentence_case(text: str) -> str:
    chars = list(text)
    upper_next = True
    for i, ch in enumerate(chars):
        if upper_next and ch.isalpha():
            chars[i] = ch.upper()
            upper_next = False
        elif ch in ".!?":
            upper_next = True
    return "".join(chars)


def _polish_text(text: str) -> str:
    text = _RE_SPACES.sub(" ", str(text or "")).strip()
    text = _RE_SPACE_PUNCT.sub(r"\1", text)
    text = text.replace("..", ".")
    seen: List[str] = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if sent and sent.lower() not in [x.lower() for x in seen]:
            seen.append(sent)
    return _polish_sentence_case(" ".join(seen))


def _polish_composed(composed: Dict[str, str]) -> Dict[str, str]:
    out = dict(composed)
    for key in ("headline", "lead", "body"):
        if key in out:
            out[key] = _polish_text(out[key])
    lead = out.get("lead", "")
    if lead and out.get("body"):
        rest = [x for x in re.split(r"(?<=[.!?])\s+", out["body"]) if x and x != lead]
        if len(rest) >= 2:
            out["body"] = " ".join(rest)
    return out


def _default_payload(state: GameState) -> Dict[str, Any]:
    g = state.groups[0] if state.groups else None
    p = state.parties[0] if state.parties else None
    c = state.candidates[0] if state.candidates else None
    pub = state.publications[0] if state.publications else None
    npc = state.npcs[0] if state.npcs else None
    return {"group": g.name if g else "", "party": p.name if p else "",
            "candidate": c.name if c else "", "publication": pub.name if pub else "",
            "npc": npc.name if npc else "", "player": state.player.name,
            "week": state.week, "village": state.village.name,
            "level": getattr(state.village, "level", "city"),
            "population": getattr(state.village, "population", 0),
            "issue": _top_issue(g), "bill": "", "promise": "", "reason": "", "tone": 0.0,
            "facts": "", "title": "", "action_title": "", "tier_word": "",
            "reactors": [], "deltas_words": [], "reason_key": "",
            "tier_distribution": {}, "tone_vector": {}}


def _ensure_payload_keys(payload: Dict[str, Any], templates: List[str]) -> Dict[str, Any]:
    needed: set = set()
    for t in templates:
        needed |= _template_fields(t)
    out = dict(payload)
    for k in needed:
        out.setdefault(k, "")
    return out


def _safe_format(template: str, payload: Dict[str, Any]) -> str:
    try:
        return template.format(**payload)
    except (KeyError, IndexError, ValueError):
        out = template
        for fld in sorted(_template_fields(template), key=len, reverse=True):
            out = out.replace("{" + fld + "}", str(payload.get(fld, "")))
        return out


def _tpl_list(name: str) -> List[str]:
    tpl = (DATA.templates if DATA else {}) or {}
    bucket = tpl.get(name)
    if isinstance(bucket, list) and bucket:
        return [str(x) for x in bucket]
    if isinstance(bucket, dict):
        flat: List[str] = []
        for v in bucket.values():
            if isinstance(v, list):
                flat.extend(str(x) for x in v)
            elif isinstance(v, str):
                flat.append(v)
        if flat:
            return flat
    raise DataError("text/templates.json: отсутствует или пуста обязательная секция '" + str(name) +
                    "'. Вшитых дефолтов нет — добавь её в JSON.")


def _svc(key: str, **kw: Any) -> str:
    tpl = (DATA.templates if DATA else {}) or {}
    msgs = tpl.get(K_TPL_SYSMSG)
    if not isinstance(msgs, dict) or key not in msgs:
        raise DataError("text/templates.json.system_messages: отсутствует ключ '" + str(key) +
                        "'. Служебные строки исходов не вшиваются в код — добавь ключ в JSON.")
    return _safe_format(str(msgs[key]), kw)


def _eff_tmpl(et: str) -> str:
    tpl = (DATA.templates if DATA else {}) or {}
    phrases = tpl.get(K_TPL_EFFPHRASE)
    if not isinstance(phrases, dict):
        raise DataError("text/templates.json: отсутствует секция 'effect_phrases' (описания эффектов). "
                        "Вшитых слов нет — добавь секцию в JSON.")
    if et in phrases:
        return str(phrases[et])
    if "unknown" in phrases:
        return str(phrases["unknown"])
    raise DataError("text/templates.json.effect_phrases: нет шаблона для типа эффекта '" + str(et) +
                    "' и нет ключа 'unknown'.")


def _compose_free(state: GameState, payload: Dict[str, Any], rng: random.Random) -> Dict[str, str]:
    headlines = _tpl_list(K_TPL_HEADLINES)
    bodies = _tpl_list(K_TPL_BODIES)
    openers = _tpl_list(K_TPL_OPENERS)
    closers = _tpl_list(K_TPL_CLOSERS)
    evals = _tpl_list(K_TPL_EVAL)
    events = _tpl_list(K_TPL_EVENT)
    conseqs = _tpl_list(K_TPL_CONSEQ)
    sources = _tpl_list(K_TPL_SOURCE)
    tpl = (DATA.templates if DATA else {}) or {}
    intros = [str(x) for x in (tpl.get(K_TPL_INTROS) or [""])]
    quotes = [str(x) for x in (tpl.get(K_TPL_QUOTES) or [""])]
    connectors = [str(x) for x in (tpl.get(K_TPL_CONNECTORS) or [""])]

    slots = {"opening": rng.choice(openers), "eval_word": rng.choice(evals),
             "event_word": rng.choice(events), "consequence_word": rng.choice(conseqs),
             "source_word": rng.choice(sources), "closer_word": rng.choice(closers),
             "intro_word": rng.choice(intros), "quote_word": rng.choice(quotes),
             "connector_word": rng.choice(connectors)}
    payload = _ensure_payload_keys({**payload, **slots}, headlines + bodies + closers)

    headline = _safe_format(rng.choice(headlines), payload)
    lead = _safe_format(rng.choice(bodies), payload)
    sentences = [_safe_format(rng.choice(bodies), payload) for _ in range(rng.randint(2, 4))]
    if rng.random() < 0.5:
        sentences.append(_safe_format(rng.choice(closers), payload))
    body = " ".join(s for s in sentences if s.strip())
    while body.count(".") < 2:
        body = (body + " " + _safe_format(rng.choice(bodies), payload)).strip()
    while body.count(".") > 7:
        cut = body.rfind(".", 0, len(body) - 1)
        if cut <= 0:
            break
        body = body[:cut + 1]
    return {"headline": headline, "lead": lead, "body": body, "reason": payload.get("reason", "")}


def _ngrams(text: str, n: int = 3) -> set:
    words = text.lower().split()
    if len(words) < n:
        return {text.lower()}
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def _overlap_ratio(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _history_window(state: GameState, weeks: int) -> List[Dict[str, Any]]:
    cutoff = state.week - weeks
    return [t for t in state.text_history if int(t.get("week", 0)) >= cutoff]


def _too_similar_history(state: GameState, text: str) -> bool:
    cand = _ngrams(text)
    for h in _history_window(state, SIMILARITY_WINDOW_WEEKS):
        old = _ngrams(str(h.get("full", "")))
        if _overlap_ratio(cand, old) >= SIMILARITY_THRESHOLD:
            return True
    return False


def _clipping_unique(state: GameState, composed: Dict[str, str]) -> bool:
    key = (composed.get("headline", ""), composed.get("lead", ""))
    recent = list(state.clippings)[-15:] + list(state.news_feed)[-15:]
    return all((i.get("headline", ""), i.get("lead", "")) != key for i in recent)


def _validate_composed(state: GameState, composed: Dict[str, str], payload: Dict[str, Any]) -> List[str]:
    problems: List[str] = []
    hl = composed.get("headline", "")
    if not (8 <= len(hl) <= 90):
        problems.append("headline length")
    body = composed.get("body", "")
    if not (2 <= body.count(".") <= 7):
        problems.append("body sentences")
    entities = [str(payload[k]) for k in ("player", "group", "party", "publication") if payload.get(k)]
    full = hl + " " + composed.get("lead", "") + " " + body
    if entities and not any(e and e in full for e in entities):
        problems.append("entity missing")
    if not _clipping_unique(state, composed):
        problems.append("duplicate")
    if _too_similar_history(state, full):
        problems.append("similar_history")
    for part in (hl, composed.get("lead", ""), body):
        if part and (_RE_EMPTY_SLOT.search(part) or "{" in part or "}" in part):
            problems.append("empty slot")
            break
    return problems


def _cap(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 3] + "..."


def _fallback_compose(p: Dict[str, Any]) -> Dict[str, str]:
    head = _cap((str(p.get("publication", "")) + ": " + str(p.get("player", "")) + " — " + str(p.get("issue", ""))).strip(), 90)
    lead = _cap((str(p.get("group", "")) + " " + str(p.get("reason", ""))).strip(), 90)
    body = _cap((str(p.get("party", "")) + " " + str(p.get("consequence_word", "")) + ". " +
                 str(p.get("npc", "")) + " " + str(p.get("source_word", ""))).strip(), 200)
    return {"headline": head, "lead": lead, "body": body, "reason": p.get("reason", "")}


def _writer_enabled() -> bool:
    nn = (DATA.nn if DATA else {}) or {}
    if not bool(nn.get("enabled_writer", False)):
        return False
    try:
        import nn_writer  # noqa: F401
        return nn_writer.available()
    except Exception:
        return False


def _compose_text(state: GameState, payload: Dict[str, Any], rng: random.Random, kind: str) -> Tuple[Dict[str, str], str]:
    base = _default_payload(state)
    base.update({k: v for k, v in (payload or {}).items() if v is not None})
    base = _fill_empty_slots(base)
    if _writer_enabled() and not state.free_generator:
        try:
            import nn_writer
            nn_writer.set_free_generator(bool(state.free_generator))
            templates = (DATA.templates if DATA else {}) or {}
            if kind == "clipping":
                res = nn_writer.compose_clipping(base, rng, templates)
                res = _polish_composed(res) if res else res
                if res and not _validate_composed(state, res, base):
                    _remember_history(state, res)
                    return res, "nn-writer"
            else:
                res = nn_writer.compose_news(base, float(base.get("tone", 0.0)),
                                             str(base.get("publication", "")), state.week, rng, templates)
                if res:
                    composed = _polish_composed({"headline": res[0], "lead": "", "body": res[1],
                                                 "reason": base.get("reason", "")})
                    if not _validate_composed(state, composed, base):
                        _remember_history(state, composed)
                        return composed, "nn-writer"
        except Exception:
            pass
    for _ in range(8):
        cand = _polish_composed(_compose_free(state, base, rng))
        if not _validate_composed(state, cand, base):
            _remember_history(state, cand)
            return cand, "gen"
    fb = _polish_composed(_fallback_compose(base))
    _remember_history(state, fb)
    return fb, "template-fallback"


def _remember_history(state: GameState, composed: Dict[str, str]) -> None:
    full = str(composed.get("headline", "")) + " " + str(composed.get("lead", "")) + " " + str(composed.get("body", ""))
    state.text_history.append({"week": state.week, "full": full, "headline": composed.get("headline", "")})
    cutoff = state.week - SIMILARITY_WINDOW_WEEKS
    state.text_history = [t for t in state.text_history if int(t.get("week", 0)) >= cutoff]
    while len(state.text_history) > 400:
        state.text_history.pop(0)


def make_clipping(state: GameState, payload: Dict[str, Any], rng: random.Random) -> Dict[str, Any]:
    composed, source = _compose_text(state, payload, rng, "clipping")
    archive_no = state.next_archive_no
    state.next_archive_no += 1
    pub = (payload or {}).get("publication", "")
    tone = float((payload or {}).get("tone", 0.0))
    clipping = {"archive_no": archive_no, "week": state.week, "publication": pub,
                "headline": composed["headline"], "lead": composed.get("lead", ""),
                "body": composed.get("body", ""), "reason": composed.get("reason", ""),
                "tone": tone, "source": source}
    state.clippings.append(clipping)
    while len(state.clippings) > 40:
        state.clippings.pop(0)
    state.news_feed.append(clipping)
    while len(state.news_feed) > 30:
        state.news_feed.pop(0)
    return clipping


def make_news_item(state: GameState, payload: Dict[str, Any], rng: random.Random) -> Dict[str, Any]:
    composed, source = _compose_text(state, payload, rng, "news")
    archive_no = state.next_archive_no
    state.next_archive_no += 1
    pub = (payload or {}).get("publication", "")
    tone = float((payload or {}).get("tone", 0.0))
    item = {"archive_no": archive_no, "week": state.week, "publication": pub,
            "headline": composed["headline"], "lead": composed.get("lead", ""),
            "body": composed.get("body", ""), "tone": tone, "source": source}
    state.news_feed.append(item)
    while len(state.news_feed) > 30:
        state.news_feed.pop(0)
    return item


def selftest_composer(state: GameState, seed: int, n: int = 200) -> List[Tuple[int, List[str], str]]:
    """Как в игре: ~3 текста в неделю, разные группы и издания, окно повторов 5 недель."""
    rng = random.Random(seed)
    violations: List[Tuple[int, List[str], str]] = []
    start_week = state.week
    for i in range(n):
        state.week = start_week + i // 3
        p = _default_payload(state)
        p["tone"] = rng.choice([-0.5, 0.0, 0.5])
        p["player"] = state.player.name
        if state.groups:
            g = state.groups[i % len(state.groups)]
            p["group"] = g.name
            p["issue"] = _top_issue(g) if rng.random() < 0.5 else rng.choice(sorted(g.issues or {"": 0}))
        if state.publications:
            p["publication"] = state.publications[i % len(state.publications)].name
        c, src = _compose_text(state, p, rng, "clipping")
        # текст уже записан в историю, поэтому similar_history/duplicate здесь проверять нельзя;
        # вместо этого считаем нарушением уход в аварийный шаблон (все 8 попыток забракованы)
        probs = [x for x in _validate_composed(state, c, _fill_empty_slots(p)) if x not in ("duplicate", "similar_history")]
        if src == "template-fallback":
            probs.append("fallback")
        if probs:
            violations.append((i, probs, c.get("headline", "")))
    state.week = start_week
    return violations


# ================= анализатор последствий (векторы чисел; слов НЕТ) =================
def _analyzer_enabled() -> bool:
    nn = (DATA.nn if DATA else {}) or {}
    if not bool(nn.get("enabled_analyzer", False)):
        return False
    try:
        import nn_analyzer  # noqa: F401
        return nn_analyzer.available()
    except Exception:
        return False


def _analyzer_cfg() -> Dict[str, Any]:
    cfg = ((DATA.nn if DATA else {}) or {}).get("analyzer", {}) or {}
    for key in (K_AN_TIER_PRIOR, K_AN_TIER_EFFECTS, K_AN_TIER_MARGINS, K_AN_CTX_WEIGHTS, K_AN_REACTION_TABLES):
        if key not in cfg:
            raise DataError("nn/analyzer.json: отсутствует обязательная секция '" + str(key) + "'. Вшитых дефолтов нет.")
    return cfg


def _round_step(x: float, step: float = 0.05) -> float:
    return round(round(x / step) * step, 2)


def _tier_from_margin(margin: int, margins: Dict[str, Any]) -> str:
    if margin <= int(margins.get("great", -30)):
        return "great"
    if margin <= int(margins.get("solid", -10)):
        return "solid"
    if margin <= int(margins.get("complication", 0)):
        return "complication"
    if margin <= int(margins.get("minor", 10)):
        return "minor"
    if margin <= int(margins.get("major", 25)):
        return "major"
    return "catastrophe"


def _distribution(tier: str, cfg: Dict[str, Any], rng: random.Random, context_shift: float) -> Dict[str, float]:
    prior = cfg[K_AN_TIER_PRIOR]
    dist: Dict[str, float] = {}
    for t in TIERS:
        base = float(prior.get(t, 0.0))
        if t == tier:
            base += 0.5
        same_sign = (TIER_SIGN.get(t, 0) == TIER_SIGN.get(tier, 0))
        base += context_shift * (1.0 if same_sign else -0.5)
        base += rng.uniform(-0.05, 0.05)
        dist[t] = max(0.0, base)
    total = sum(dist.values()) or 1.0
    dist = {t: _round_step(v / total) for t, v in dist.items()}
    diff = round(1.0 - sum(dist.values()), 2)
    if abs(diff) >= 0.01:
        top = max(dist, key=lambda k: dist[k])
        dist[top] = _round_step(dist[top] + diff)
    return dist


def _tone_vector(tier: str, mag: int) -> Dict[str, float]:
    sign = TIER_SIGN.get(tier, 0)
    intensity = min(1.0, mag / 3.0)
    return {"polarity": _round_step(sign * intensity), "intensity": _round_step(intensity)}


def _reason_key(state: GameState, action: ActionData) -> str:
    pl = state.player
    if pl.prison_status != PrisonStatus.FREE:
        return "context"
    if getattr(action, "secret", False) and float(getattr(action, "illegality", 0.0)) >= 0.3:
        return "illegality"
    if int(getattr(action, "risk", 0)) >= 40:
        return "resistance"
    if (int(pl.fatigue) + int(pl.stress)) >= 60:
        return "fatigue"
    return "luck"


def _context_shift(state: GameState, action: ActionData, cfg: Dict[str, Any]) -> float:
    cw = cfg[K_AN_CTX_WEIGHTS]
    shift = 0.0
    pl = state.player
    if pl.prison_status != PrisonStatus.FREE:
        shift += float(cw.get("prison_penalty", 0.0))
    if pl.role == Role.MAYOR:
        shift += float(cw.get("mayor_bonus", 0.0))
    elif pl.role == Role.COUNCILOR:
        shift += float(cw.get("councilor_bonus", 0.0))
    elif pl.role == Role.OUTSIDER:
        shift += float(cw.get("opposition_penalty", 0.0))
    return shift


def _group_name(state: GameState, group_id: str) -> str:
    g = get_group(state, group_id)
    return g.name if g else str(group_id)


def _eff_phrase(state: GameState, eff: Dict[str, Any]) -> str:
    et = str(eff.get(K_EFF_TYPE, ""))
    d = int(eff.get(K_EFF_DELTA, 0))
    if et == "group_mood" or et == "group_loyalty":
        return _safe_format(_eff_tmpl(et), {"name": _group_name(state, str(eff.get(K_EFF_GROUP, ""))), "delta": d})
    if et == "player_stat":
        return _safe_format(_eff_tmpl(et), {"stat": str(eff.get(K_EFF_STAT, "")), "delta": d})
    if et == "treasury":
        return _safe_format(_eff_tmpl(et), {"delta": d})
    if et == "player_money":
        return _safe_format(_eff_tmpl(et), {"delta": d})
    if et == "support":
        return _safe_format(_eff_tmpl(et), {"subject": str(eff.get(K_EFF_SUBJECT, "")),
                                            "kind": str(eff.get(K_EFF_KIND, "candidate")), "delta": d})
    return _safe_format(_eff_tmpl("unknown"), {"et": et, "delta": d})


def _effects_to_words(state: GameState, script: Dict[str, Any]) -> List[str]:
    return [_eff_phrase(state, e) for e in script.get(K_EFFECTS, [])]


def _apply_script_effects(state: GameState, script: Dict[str, Any]) -> None:
    for eff in script.get(K_EFFECTS, []):
        et = eff.get(K_EFF_TYPE)
        if _apply_world_effect(state, eff):
            continue
        if et == "group_mood":
            g = get_group(state, eff.get(K_EFF_GROUP, ""))
            if g:
                g.mood = clamp(g.mood + int(eff.get(K_EFF_DELTA, 0)), 0, 100)
        elif et == "group_loyalty":
            g = get_group(state, eff.get(K_EFF_GROUP, ""))
            if g:
                g.loyalty = clamp(g.loyalty + int(eff.get(K_EFF_DELTA, 0)), 0, 100)
        elif et == "player_stat":
            stat = eff.get(K_EFF_STAT, "trust")
            cur = int(getattr(state.player, stat, 0))
            setattr(state.player, stat, clamp(cur + _diminish(stat, cur, int(eff.get(K_EFF_DELTA, 0))), 0, 100))
        elif et == "treasury":
            state.treasury += int(eff.get(K_EFF_DELTA, 0))
        elif et == "player_money":
            state.player.money += int(eff.get(K_EFF_DELTA, 0))
        elif et == "support":
            g = get_group(state, eff.get(K_EFF_GROUP, ""))
            if g:
                kind = eff.get(K_EFF_KIND, "candidate")
                subj = eff.get(K_EFF_SUBJECT, "")
                bucket = g.candidate_support if kind == "candidate" else g.party_support
                bucket[subj] = max(0, int(bucket.get(subj, 0)) + int(eff.get(K_EFF_DELTA, 0)))


def fallback_analyze_action(state: GameState, action: ActionData, tier: str, rng: random.Random) -> Dict[str, Any]:
    if _analyzer_enabled():
        try:
            import nn_analyzer
            return nn_analyzer.analyze_action(state, action, tier, rng)
        except Exception:
            pass
    cfg = _analyzer_cfg()
    te = cfg[K_AN_TIER_EFFECTS].get(tier, {})
    mag = int(te.get("primary_delta", 1))
    sec_mag = int(te.get("secondary_delta", 0))
    reactor_chance = float(te.get("reactor_chance", 0.5))
    sign = TIER_SIGN.get(tier, 0)
    effects: List[Dict[str, Any]] = []
    reactors: List[str] = []
    group = get_group(state, action.target_group_id)
    if group:
        if sign != 0:
            effects.append({"type": "group_mood", "group": group.id, "delta": sign * mag * 3})
            effects.append({"type": "group_loyalty", "group": group.id, "delta": sign * mag * 2})
            effects.append({"type": "support", "group": group.id, "kind": "candidate",
                            "subject": state.player.name, "delta": sign * mag * 50})
        reactors.append(group.name)
    pl = state.player
    if sign > 0:
        effects.append({"type": "player_stat", "stat": "awareness", "delta": mag})
        effects.append({"type": "player_stat", "stat": "trust", "delta": max(1, mag - 1)})
    elif sign < 0:
        effects.append({"type": "player_stat", "stat": "anti_awareness", "delta": mag})
    if action.intent == "attack":
        effects.append({"type": "player_stat", "stat": "threat", "delta": mag})
        cand = get_candidate(state, action.target_candidate_id)
        if cand:
            effects.append({"type": "support", "group": (group.id if group else ""),
                            "kind": "candidate", "subject": cand.name, "delta": -sign * mag * 30})
            reactors.append(cand.name)
    if reactors and rng.random() < reactor_chance and state.publications:
        reactors.append(state.publications[0].name)
    if sec_mag and rng.random() < float(cfg.get(K_AN_SECONDARY_CHANCE, 0.5)):
        party = state.parties[0] if state.parties else None
        if party:
            effects.append({"type": "support", "group": (group.id if group else ""),
                            "kind": "party", "subject": party.name, "delta": sign * sec_mag * 20})
            reactors.append(party.name)
    reason_key = _reason_key(state, action)
    ctx_shift = _context_shift(state, action, cfg)
    distribution = _distribution(tier, cfg, rng, ctx_shift)
    tone_vector = _tone_vector(tier, mag)
    tone = round(tone_vector["polarity"], 2)
    primary = str(action.title) + ": " + tier_label(tier)
    secondary: List[str] = []
    for eff in effects[1:]:
        secondary.append(_eff_phrase(state, eff))
    if reactors:
        secondary.append(_svc("reactors_prefix", reactors=", ".join(reactors)))
    plaus = round(min(1.0, float(cfg.get(K_AN_PLAUS_BASE, 0.75)) + rng.uniform(-0.05, 0.15)), 2)
    return {"primary": primary, "secondary": secondary, "reactors": reactors,
            "tone": tone, "tone_vector": tone_vector, "tier_distribution": distribution,
            "reason_key": reason_key, "effects": effects, "plausibility": plaus, "delayed": []}


def fallback_law_forecast(state: GameState, law: Dict[str, Any], rng: random.Random) -> Dict[str, Any]:
    if _analyzer_enabled():
        try:
            import nn_analyzer
            return nn_analyzer.analyze_law_forecast(state, law, rng)
        except Exception:
            pass
    cfg = _analyzer_cfg()
    skeleton = law.get("typed_skeleton", {}) or {}
    predicate = str(skeleton.get("predicate", "символический"))
    effects: List[Dict[str, Any]] = []
    reactors: List[str] = []
    tone = 0.0
    negative_pred = predicate in ("запретить", "ограничить", "налог")
    positive_pred = predicate in ("разрешить", "финансировать", "субсидия")
    for obj in skeleton.get("objects", []) or []:
        group = get_group(state, obj)
        if group is not None:
            delta = -3 if negative_pred else (3 if positive_pred else 0)
            if delta:
                effects.append({"type": "group_mood", "group": group.id, "delta": delta})
                effects.append({"type": "support", "group": group.id, "kind": "candidate",
                                "subject": state.player.name, "delta": delta * 40})
            reactors.append(group.name)
            tone += 0.1 * (1 if delta > 0 else (-1 if delta < 0 else 0))
        else:
            reactors.append(str(obj))
    if predicate in ("финансировать", "субсидия") or skeleton.get("budget") == "казна":
        effects.append({"type": "treasury", "delta": -10})
    if predicate == "налог" or skeleton.get("budget") == "налог":
        effects.append({"type": "treasury", "delta": 8})
    if skeleton.get("enforcement") == "надзор":
        effects.append({"type": "treasury", "delta": -4})
    if skeleton.get("enforcement") == "штраф":
        effects.append({"type": "treasury", "delta": 5})
    tier = "solid" if tone > 0.1 else ("minor" if tone < -0.1 else "complication")
    distribution = _distribution(tier, cfg, rng, 0.0)
    tone_vector = _tone_vector(tier, 2)
    primary = _svc("law_forecast_primary", title=str(law.get("title", "")), predicate=predicate)
    secondary: List[str] = [_eff_phrase(state, e) for e in effects[1:]]
    if reactors:
        secondary.append(_svc("reactors_prefix", reactors=", ".join(reactors)))
    plaus = round(min(1.0, float(cfg.get(K_AN_PLAUS_BASE, 0.75)) + rng.uniform(-0.05, 0.1)), 2)
    return {"primary": primary, "secondary": secondary, "reactors": reactors,
            "tone": round(tone, 2), "tone_vector": tone_vector, "tier_distribution": distribution,
            "reason_key": "context", "effects": effects, "plausibility": plaus, "delayed": []}


def drift_script(script: Dict[str, Any], rng: random.Random, bound: Optional[int] = None) -> Dict[str, Any]:
    if _analyzer_enabled():
        try:
            import nn_analyzer
            return nn_analyzer.produce_actual(script, None, rng)
        except Exception:
            pass
    if bound is None:
        cfg = ((DATA.nn if DATA else {}) or {}).get("analyzer", {}) or {}
        bound = int(cfg.get(K_AN_DRIFT_BOUND, 1))
    actual = json.loads(json.dumps(script))
    for eff in actual.get(K_EFFECTS, []):
        if K_EFF_DELTA in eff:
            eff[K_EFF_DELTA] = int(eff[K_EFF_DELTA]) + rng.randint(-bound, bound)
    actual["primary"] = str(script.get("primary", "")) + " " + _svc("fact_suffix")
    return actual


def analyze_action(state: GameState, action: ActionData, tier: str, rng: random.Random) -> Dict[str, Any]:
    return fallback_analyze_action(state, action, tier, rng)


def analyze_law(state: GameState, law: Dict[str, Any], rng: random.Random) -> Dict[str, Any]:
    return fallback_law_forecast(state, law, rng)


# ================= свободные законы =================
def create_custom_law(state: GameState, player_text: str, typed_skeleton: Dict[str, Any]) -> Tuple[bool, str]:
    if not player_text.strip():
        return False, _svc("law_needs_body")
    law = {"id": "custom_" + str(len(state.custom_laws) + 1), "title": player_text.strip()[:60],
           "player_text": player_text.strip(), "typed_skeleton": typed_skeleton,
           "forecast_script": {}, "status": "discussion", "enacted_week": 0, "actual_scripts": []}
    state.custom_laws.append(law)
    state.bills.append({"id": law["id"], "template_id": law["id"], "title": law["title"],
                        "stage": "discussion", "weekly_cost": 1, "custom": True})
    add_log(state, "Внесён свободный закон: " + law["title"])
    return True, _svc("law_created", title=law["title"])


def law_template(state: GameState, template_id: str) -> Dict[str, Any]:
    laws = (DATA.laws if DATA else {}) or {}
    for t in laws.get("templates", []) or []:
        if t.get(K_ACTION_ID) == template_id:
            return t
    for law in state.custom_laws:
        if law["id"] == template_id:
            return {K_ACTION_ID: law["id"], K_TITLE: law["title"], "act_type": "law",
                    "weekly_cost": 1, K_EFFECTS: [], "custom": True,
                    "player_text": law.get("player_text", ""), "typed_skeleton": law.get("typed_skeleton", {})}
    return {}


def _required_votes(state: GameState, template: Dict[str, Any]) -> int:
    laws = (DATA.laws if DATA else {}) or {}
    cfg = laws.get("act_types", {}).get(template.get("act_type", "law"), {})
    if template.get("target_electoral_system"):
        return int((DATA.electoral if DATA else {}).get("reform", {}).get("required_votes", 4))
    if template.get("act_type") == "constitutional":
        return int(cfg.get("qualified_majority", 5))
    return int(cfg.get("simple_majority", 4))


def _enact_bill(state: GameState, bill: Dict[str, Any], rng: random.Random) -> None:
    template = law_template(state, bill.get("template_id", ""))
    bill["stage"] = "enacted"
    for eff in template.get(K_EFFECTS, []) or []:
        _apply_script_effects(state, {K_EFFECTS: [eff]})
    state.enacted_laws.append({K_ACTION_ID: template.get(K_ACTION_ID, bill.get("template_id", "law")),
                               K_TITLE: bill.get(K_TITLE, ""), "enacted_week": state.week,
                               "weekly_cost": int(template.get("weekly_cost", 0))})
    target_system = template.get("target_electoral_system")
    if target_system in [e.value for e in ElectoralSystem]:
        state.electoral_system = ElectoralSystem(target_system)
        add_log(state, "Избирательная система изменена на " + state.electoral_system.value + ".")
    if template.get("custom"):
        for law in state.custom_laws:
            if law["id"] == template[K_ACTION_ID]:
                law["status"] = "enacted"
                law["enacted_week"] = state.week
                law["forecast_script"] = analyze_law(state, law, rng)
    add_log(state, "Закон принят: " + str(bill.get(K_TITLE, "")))


def tick_bills(state: GameState, rng: random.Random) -> None:
    remaining: List[Dict[str, Any]] = []
    for bill in state.bills:
        template = law_template(state, bill.get("template_id", ""))
        stage = bill.get("stage", "discussion")
        if stage == "discussion":
            required = _required_votes(state, template)
            favorable = state.council_seats
            if favorable >= required:
                bill["stage"] = "sign"
                add_log(state, "Совет одобрил «" + str(bill.get(K_TITLE, "")) + "» (" + str(favorable) + "/" + str(required) + ").")
                remaining.append(bill)
            else:
                add_log(state, "Совет отклонил «" + str(bill.get(K_TITLE, "")) + "» (" + str(favorable) + "/" + str(required) + ").")
                for law in state.custom_laws:
                    if law["id"] == bill.get("template_id"):
                        law["status"] = "rejected"
        elif stage == "sign":
            if rng.random() < 0.25:
                bill["stage"] = "veto"
                add_log(state, "Мэр наложил вето на «" + str(bill.get(K_TITLE, "")) + "».")
                remaining.append(bill)
            else:
                _enact_bill(state, bill, rng)
        elif stage == "veto":
            remaining.append(bill)
    state.bills = remaining


def override_veto(state: GameState) -> str:
    laws = (DATA.laws if DATA else {}) or {}
    needed = int(laws.get("veto", {}).get("override_votes", 5))
    for bill in list(state.bills):
        if bill.get("stage") == "veto":
            if state.council_seats >= needed:
                state.bills.remove(bill)
                _enact_bill(state, bill, get_week_rng(state, 999))
                return _svc("veto_overridden", seats=state.council_seats, needed=needed)
            return _svc("veto_insufficient", seats=state.council_seats, needed=needed)
    return _svc("veto_none")


# ================= парламент и выборы (ВЫБОРЫ НЕ ЗАВЕРШАЮТ ИГРУ) =================
def party_votes(state: GameState) -> Dict[str, float]:
    votes = {p.id: float(p.popularity) + float(p.trust_to_player) * 0.3 for p in state.parties}
    votes["player"] = float(state.player.awareness) * 0.5 + float(state.player.trust) * 0.5
    return votes


def distribute_parliament(state: GameState, rng: random.Random) -> Dict[str, int]:
    total = calculate_council(state, state.electoral_system)
    votes = party_votes(state)
    valid = sum(votes.values()) or 1.0
    seats: Dict[str, int] = {pid: 0 for pid in votes}
    if state.electoral_system == ElectoralSystem.MAJORITARIAN:
        ordered = sorted(votes.items(), key=lambda kv: kv[1], reverse=True)
        for i in range(total):
            seats[ordered[i % len(ordered)][0]] += 1
    else:
        quota = valid / total
        remainders: List[Tuple[float, str]] = []
        allocated = 0
        for pid, v in votes.items():
            base = int(v // quota) if quota else 0
            seats[pid] = base
            allocated += base
            remainders.append((v / quota - base, pid))
        remainders.sort(reverse=True)
        i = 0
        while allocated < total and remainders:
            seats[remainders[i % len(remainders)][1]] += 1
            allocated += 1
            i += 1
    state.parliament_seats = seats
    state.council_seats = seats.get("player", 0)
    for party in state.parties:
        party.seats = seats.get(party.id, 0)
    return seats


def _run_elections(state: GameState, rng: random.Random) -> None:
    distribute_parliament(state, rng)
    pl = state.player
    ecfg = _wcfg("election")
    if ecfg:
        pw, rw = ecfg.get("player") or {}, ecfg.get("rival") or {}
        score = int(round(pl.awareness * float(pw.get("awareness", 1)) + pl.trust * float(pw.get("trust", 1))
                          + pl.anti_awareness * float(pw.get("anti_awareness", -1))
                          + state.council_seats * float(pw.get("seat", 5))
                          + rng.uniform(-float(ecfg.get("noise", 0)), float(ecfg.get("noise", 0)))))
        inc_id = str(_wcfg("emergent").get("incumbent_candidate", ""))
        best = 0
        for c in state.candidates:
            v = c.popularity * float(rw.get("popularity", 1)) + c.scandal * float(rw.get("scandal", -1))
            if c.id == inc_id:
                v += float(ecfg.get("incumbent_bonus", 0))
            best = max(best, int(round(v)))
    else:
        score = pl.awareness + pl.trust - pl.anti_awareness + state.council_seats * 5
        rivals = sorted(state.candidates, key=lambda c: c.popularity - c.scandal, reverse=True)
        best = (rivals[0].popularity - rivals[0].scandal) if rivals else 0
    won = score > best
    pl.role = Role.COUNCILOR if (won and state.electoral_system == ElectoralSystem.PROPORTIONAL) \
        else (Role.MAYOR if won else Role.OUTSIDER)
    pl.got_mandate = won
    # КРИТИЧНЫЙ ФИКС: выборы НЕ завершают игру. Game over — только смерть.
    pl.legacy_tags.append("мандат получен" if won else "мандат не получен")
    state.election_count += 1
    period = int(((DATA.village if DATA else {}) or {}).get("election", {}).get("period_weeks", 48))
    state.next_election_week = state.week + period
    add_log(state, "Выборы: " + ("победа" if won else "поражение") + " (" + str(score) + " против " + str(best) +
            "). Следующие выборы на неделе " + str(state.next_election_week) + ".")


# ================= недельные ходы =================
def _week_facts(state: GameState, rng: random.Random) -> List[WeekFact]:
    facts: List[WeekFact] = []
    for i in range(rng.randint(1, 2)):
        pub = rng.choice(state.publications) if state.publications else None
        group = rng.choice(state.groups) if state.groups else None
        party = rng.choice(state.parties) if state.parties else None
        base_tone = round(rng.uniform(-0.6, 0.6), 2)
        payload = {"publication": pub.name if pub else "",
                   "tone": round(base_tone + (pub.tone if pub else 0.0), 2),
                   "reason": "события недели", "group": group.name if group else "",
                   "party": party.name if party else "", "player": state.player.name,
                   "facts": "факты недели", "level": getattr(state.village, "level", "city"),
                   "population": getattr(state.village, "population", 0)}
        facts.append(WeekFact(id="fact_" + str(state.week) + "_" + str(i), kind="event",
                              tone=payload["tone"], text="", payload=payload))
    return facts


def _npc_moves(state: GameState, rng: random.Random) -> None:
    for npc in state.npcs:
        npc.loyalty = clamp(npc.loyalty + rng.randint(-3, 3), 0, 100)
        if state.player.evidence > 40 and rng.random() < 0.2:
            state.player.threat = clamp(state.player.threat + 3, 0, 100)


def _candidate_moves(state: GameState, rng: random.Random) -> None:
    for cand in state.candidates:
        cand.popularity = clamp(cand.popularity + rng.randint(-2, 3), 0, 100)
        cand.scandal = clamp(cand.scandal + rng.randint(-2, 2), 0, 100)


def _party_reactions(state: GameState, rng: random.Random) -> None:
    for party in state.parties:
        drift = rng.randint(-2, 2) + (1 if party.trust_to_player > 60 else -1 if party.trust_to_player < 40 else 0)
        party.popularity = clamp(party.popularity + drift, 0, 100)


def _justice_tick(state: GameState, rng: random.Random, cfg: Dict[str, Any]) -> None:
    """Правосудие из world.json: тюрьма — эпизод кампании, а не медленная смерть."""
    pl = state.player
    js = state.world.setdefault("justice", {"since": 0, "release_week": 0})
    inv_max = int(_bal(K_BAL_INVESTIGATION_MAX))
    name = pl.name
    free = pl.prison_status == PrisonStatus.FREE
    if free:
        if pl.evidence > 0:
            pl.investigation = clamp(pl.investigation + rng.randint(2, 6), 0, inv_max)
            pl.evidence = clamp(pl.evidence - int(cfg.get("evidence_decay", 0)), 0, 100)
        else:
            pl.investigation = clamp(pl.investigation - 2, 0, inv_max)
        if pl.investigation >= inv_max:
            pl.prison_status = PrisonStatus.DETAINED
            js["since"] = state.week
            add_log(state, "Игрок задержан по делу.")
    elif pl.prison_status == PrisonStatus.DETAINED:
        if pl.evidence < int(cfg.get("detained_release_if_evidence_below", 0)):
            pl.prison_status = PrisonStatus.FREE
            pl.investigation = int(inv_max * 0.5)
            add_log(state, "Задержание: улик мало, отпущен под подписку.")
        elif rng.random() < float(cfg.get("arrest_chance", 0.5)):
            pl.prison_status = PrisonStatus.ARRESTED
            add_log(state, "Задержание перешло в арест. Суд через " + str(cfg.get("trial_after_weeks", 3)) + " нед.")
    elif pl.prison_status == PrisonStatus.ARRESTED:
        if state.week - int(js.get("since", state.week)) >= int(cfg.get("trial_after_weeks", 3)):
            v = cfg.get("verdict") or {}
            spend = min(pl.money, int(v.get("lawyer_max_spend", 0)))
            pl.money -= spend
            score = pl.evidence * float(v.get("evidence_weight", 1.5)) \
                - pl.connections * float(v.get("connections_weight", 0.6)) \
                - pl.security * float(v.get("security_weight", 0.3)) \
                - spend / 100.0 * float(v.get("lawyer_per_100", 6)) \
                + rng.uniform(-float(v.get("random", 25)), float(v.get("random", 25)))
            if spend:
                add_log(state, "Адвокаты обошлись в " + str(spend) + ".")
            if score < float(v.get("threshold", 45)):
                ac = cfg.get("acquit") or {}
                pl.prison_status = PrisonStatus.FREE
                pl.evidence = int(pl.evidence * float(ac.get("evidence_mult", 0.5)))
                pl.investigation = int(ac.get("investigation", 30))
                pl.trust = clamp(pl.trust + int(ac.get("trust", 0)), 0, 100)
                add_log(state, _safe_format(str(ac.get("log", "Оправдан.")), {"name": name}))
            else:
                se = cfg.get("sentence") or {}
                weeks = min(int(se.get("max_weeks", 16)),
                            int(se.get("base_weeks", 4)) + int(pl.evidence * float(se.get("per_evidence", 0.1))))
                pl.prison_status = PrisonStatus.PRISON
                js["release_week"] = state.week + weeks
                pl.trust = clamp(pl.trust + int(se.get("trust", 0)), 0, 100)
                pl.awareness = clamp(pl.awareness + int(se.get("awareness", 0)), 0, 100)
                add_log(state, _safe_format(str(se.get("log", "Приговор: {weeks} нед.")), {"name": name, "weeks": weeks}))
    elif pl.prison_status == PrisonStatus.PRISON:
        if state.week >= int(js.get("release_week", 0)):
            rel = cfg.get("release") or {}
            pl.prison_status = PrisonStatus.FREE
            pl.evidence = 0
            pl.investigation = 0
            if rel.get("legacy") and rel.get("legacy") not in pl.legacy_tags:
                pl.legacy_tags.append(str(rel.get("legacy")))
            add_log(state, _safe_format(str(rel.get("log", "Освобождён.")), {"name": name}))
    if pl.prison_status == PrisonStatus.FREE:
        pl.health = clamp(pl.health + int(cfg.get("recovery_health", 0)), 0, 100)
        pl.stress = clamp(pl.stress - int(cfg.get("recovery_stress", 0)), 0, 100)
    else:
        floor = int(cfg.get("custody_health_floor", 15))
        if pl.health > floor:
            pl.health = max(floor, pl.health - int(cfg.get("custody_health_drain", 3)))
        pl.stress = clamp(pl.stress + int(cfg.get("custody_stress", 4)), 0, 100)
    # покушения при высокой угрозе — единственный путь к смерти кроме старых механик
    pl.threat = clamp(pl.threat - int(cfg.get("threat_decay", 0)), 0, 100)
    asn = cfg.get("assassination") or {}
    over = pl.threat - int(asn.get("min_threat", 101))
    if asn and over >= 0:
        chance = (over + 1) * float(asn.get("chance_per_point", 0.0))
        if pl.prison_status != PrisonStatus.FREE:
            chance *= float(asn.get("custody_mult", 1.0))
        if rng.random() < chance:
            dmg = rng.randint(int(asn.get("damage_min", 20)), int(asn.get("damage_max", 60)))
            dmg = max(1, int(dmg - pl.security * float(asn.get("security_reduce", 0.5))))
            pl.health = clamp(pl.health - dmg, 0, 100)
            add_log(state, _safe_format(str(asn.get("log", "Покушение!")), {"name": name, "dmg": dmg}))
            pub = rng.choice(state.publications) if state.publications else None
            push_story(state, pub.name if pub else "", _safe_format(str(asn.get("headline", "")), {"name": name}),
                       "", -0.6)


def _prison_tick(state: GameState, rng: random.Random) -> None:
    pl = state.player
    jcfg = _wcfg("justice")
    if jcfg:
        _justice_tick(state, rng, jcfg)
        return
    inv_max = int(_bal(K_BAL_INVESTIGATION_MAX))
    if pl.evidence > 0:
        pl.investigation = clamp(pl.investigation + rng.randint(2, 6), 0, inv_max)
    if pl.investigation >= inv_max and pl.prison_status == PrisonStatus.FREE:
        pl.prison_status = PrisonStatus.DETAINED
        add_log(state, "Игрок задержан по делу.")
    if pl.prison_status == PrisonStatus.DETAINED and rng.random() < 0.3:
        pl.prison_status = PrisonStatus.ARRESTED
        add_log(state, "Задержание перешло в арест.")
    if pl.prison_status in (PrisonStatus.DETAINED, PrisonStatus.ARRESTED):
        pl.health = clamp(pl.health - 5, 0, 100)
        pl.stress = clamp(pl.stress + 5, 0, 100)


def _player_death(state: GameState) -> None:
    state.is_game_over = True
    state.game_over_reason = "death"
    state.player.legacy_tags.append("погиб в кампании")
    add_log(state, "Игрок погиб. Кампания завершена.")


# ================= универсальный резолвер (НЕ применяет effects; ревизия решает) =================
def resolve_action(state: GameState, action: ActionData, rng: random.Random) -> Tuple[bool, bool, str, Dict[str, Any], Dict[str, Any]]:
    skill_name = str(getattr(action, "skill", "") or _bal(K_BAL_DEFAULT_SKILL))
    if skill_name not in SKILL_FIELDS:
        raise DataError("actions.json: действие '" + str(action.id) + "' ссылается на неизвестный навык '" +
                        str(skill_name) + "'. Допустимо: " + str(sorted(SKILL_FIELDS)) + ".")
    modifier = int(getattr(state.player, skill_name, 0))
    difficulty = int(getattr(action, "difficulty", 0) or _bal(K_BAL_DEFAULT_DIFF))
    raw, total, ok = roll_d100(rng, modifier=modifier, difficulty=difficulty)
    margin = total - difficulty
    cfg = _analyzer_cfg()
    # шкала тиров: отрицательная разница = успех (great <= -30 ... catastrophe > 25).
    # Раньше успех передавался с плюсом и превращался в «провал/катастрофу».
    tier = _tier_from_margin(-margin, cfg[K_AN_TIER_MARGINS])
    script = analyze_action(state, action, tier, rng)
    if str(script.get("primary", "")).endswith(": " + tier):
        script["primary"] = str(script["primary"])[: -len(tier)] + tier_label(tier)
    world_effects(state, action, tier, rng, script)
    group = get_group(state, action.target_group_id)
    pub = get_publication(state, "")
    payload = {"tone": script.get("tone", 0.0), "reason": script.get("primary", action.title),
               "group": group.name if group else "", "publication": pub.name if pub else "",
               "title": action.title, "action_title": action.title, "tier_word": tier,
               "reactors": script.get("reactors", []), "deltas_words": _effects_to_words(state, script),
               "reason_key": script.get("reason_key", "luck"),
               "tier_distribution": script.get("tier_distribution", {}),
               "tone_vector": script.get("tone_vector", {}),
               "issue": action.issue or "", "week": state.week,
               "level": getattr(state.village, "level", "city"),
               "population": getattr(state.village, "population", 0)}
    tags = list(getattr(action, "tags", []) or [])
    secret = "secret" in tags or bool(getattr(action, "secret", False))
    if secret and TIER_SIGN.get(tier, 0) >= 0:
        clipping: Dict[str, Any] = {}      # тайное при успехе в газеты не попадает
    else:
        clipping = make_clipping(state, payload, rng)
        _free_headline(state, action, clipping, leak=secret)
    base_msg = _svc("roll_report", title=action.title, total=total, difficulty=difficulty, tier=tier_label(tier))
    arc_no = clipping.get("archive_no", "?")
    wk = clipping.get("week", "?")
    head = clipping.get("headline", "")
    lead = clipping.get("lead", "")
    body = clipping.get("body", "")
    reason = clipping.get("reason", "")
    src = clipping.get("source", "")
    text = "".join([base_msg, "\n", _svc("clipping_prefix", no=arc_no, wk=wk), head, " | ", lead, " | ", body,
                    " | ", _svc("clipping_reason"), reason])
    if state.detail_level == "полно":
        text += " | " + _svc("clipping_source") + src
        td = script.get("tier_distribution", {})
        text += " | " + _svc("clipping_tier") + str(td)
    return True, ok, text, script, clipping


# ================= живой мир: теги, НПС, заявления, события, соперники, доход =================
def tier_label(tier: str) -> str:
    return str((_wcfg("tier_labels") or {}).get(tier, tier))


def _free_headline(state: GameState, action: ActionData, clipping: Dict[str, Any], leak: bool = False) -> None:
    cfg = _wcfg("free_news")
    raw = str(getattr(action, "raw", "") or "")
    if not cfg or not clipping or (action.id != _free_id() and not leak):
        return
    target = ""
    if action.target_group_id:
        target = _group_name(state, action.target_group_id)
    elif action.target_candidate_id:
        c = get_candidate(state, action.target_candidate_id)
        target = c.name if c else ""
    npc_id = getattr(action, "target_npc_id", "")
    if not target and npc_id:
        target = next((n.name for n in state.npcs if n.id == npc_id), "")
    slots = {"player": state.player.name, "target": target or str(cfg.get("default_target", "")),
             "raw": raw or action.title}
    if leak:
        clipping["headline"] = _safe_format(str(cfg.get("leak_headline", "")), slots)
        clipping["body"] = _safe_format(str(cfg.get("leak_body", "")), slots)
        clipping["lead"] = ""
        clipping["tone"] = -0.5
        return
    tags = list(getattr(action, "tags", []) or [])
    heads = cfg.get("headlines") or {}
    key = next((t for t in (cfg.get("order") or []) if t in tags and t in heads), "default")
    clipping["headline"] = _safe_format(str(heads.get(key, "")), slots)

def _wcfg(key: str) -> Dict[str, Any]:
    return dict((((DATA.world if DATA else {}) or {}).get(key)) or {})


def _clone_action(base: ActionData, **changes: Any) -> ActionData:
    """dataclasses.replace теряет setattr-поля (skill/difficulty/effects…) — копируем их."""
    new = _replace(base, **changes)
    for k, v in base.__dict__.items():
        if k not in new.__dict__:
            setattr(new, k, v)
    return new


def _free_id() -> str:
    return str(_wcfg("free_action").get("action_id", "free_action"))


def push_story(state: GameState, publication: str, headline: str, body: str, tone: float,
               kind: str = "story") -> Dict[str, Any]:
    archive_no = state.next_archive_no
    state.next_archive_no += 1
    item = {"archive_no": archive_no, "week": state.week, "publication": publication,
            "headline": _polish_text(headline), "lead": "", "body": _polish_text(body),
            "tone": float(tone), "source": kind}
    state.news_feed.append(item)
    state.clippings.append(item)
    while len(state.news_feed) > 30:
        state.news_feed.pop(0)
    while len(state.clippings) > 40:
        state.clippings.pop(0)
    return item


def tag_cost(tags: List[str]) -> int:
    tcfg = _wcfg("tags")
    return sum(int((tcfg.get(t) or {}).get("cost", 0)) for t in tags or [])


def _hot_groups(state: GameState) -> Dict[str, Any]:
    hot = state.world.get("hot_groups") or {}
    return {gid: v for gid, v in hot.items() if int(v.get("until", 0)) >= state.week}


def _leading_rival(state: GameState) -> Any:
    if not state.candidates:
        return None
    return max(state.candidates, key=lambda c: (c.popularity - c.scandal, c.id))


def _apply_world_meta(state: GameState, action: ActionData, qa: Dict[str, Any]) -> ActionData:
    tags = [str(t) for t in (qa.get("tags") or [])]
    tcfg = _wcfg("tags")
    fcfg = _wcfg("free_action")
    is_free = action.id == _free_id()
    changes: Dict[str, Any] = {}
    target = str(qa.get("target", "") or "")
    npc = None
    for n in state.npcs:
        if n.id == target:
            npc = n
    if is_free:
        raw = str(qa.get("raw", "") or "")
        short = raw if len(raw) <= 48 else raw[:45] + "..."
        changes["title"] = str(fcfg.get("title_prefix", "Своё действие")) + ": «" + short + "»"
        if any(c.id == target for c in state.candidates):
            changes["target_candidate_id"] = target
    new = _clone_action(action, **changes) if changes else _clone_action(action)
    diff = int(getattr(new, "difficulty", 0) or _bal(K_BAL_DEFAULT_DIFF))
    if is_free:
        diff = int(fcfg.get("base_difficulty", diff))
        skills = [str((tcfg.get(t) or {}).get("skill", "")) for t in tags if (tcfg.get(t) or {}).get("skill")]
        if skills:
            setattr(new, "skill", max(sorted(set(skills)), key=skills.count))
    diff += sum(int((tcfg.get(t) or {}).get("difficulty", 0)) for t in tags
                if is_free or t in ("secret", "illegal"))
    if new.target_group_id and new.target_group_id in _hot_groups(state):
        diff -= int(fcfg.get("hot_group_bonus", 10))
    diff = clamp(diff, int(fcfg.get("min_difficulty", 5)), int(fcfg.get("max_difficulty", 95)))
    setattr(new, "difficulty", diff)
    setattr(new, "tags", tags)
    setattr(new, "stance", str(qa.get("stance", "") or ""))
    setattr(new, "offer", str(qa.get("offer", "") or ""))
    setattr(new, "raw", str(qa.get("raw", "") or ""))
    setattr(new, "target_npc_id", npc.id if npc else "")
    setattr(new, "is_free", is_free)
    return new


def estimate_chance(state: GameState, qa: Dict[str, Any]) -> int:
    """Шанс успеха в процентах: P(d100 + навык >= сложность)."""
    action = _effective_action(state, qa)
    if not action:
        return 0
    skill = str(getattr(action, "skill", "") or _bal(K_BAL_DEFAULT_SKILL))
    mod = int(getattr(state.player, skill, 0)) if skill in SKILL_FIELDS else 0
    diff = int(getattr(action, "difficulty", 0) or _bal(K_BAL_DEFAULT_DIFF))
    need = diff - mod
    return int(clamp(101 - need, 0, 100))


def _scaled(delta: Any, scale: float) -> int:
    d = float(delta) * scale
    if d == 0:
        return 0
    v = int(round(d))
    if v == 0:
        v = 1 if d > 0 else -1
    return v


def _resolve_tag_effect(state: GameState, action: ActionData, spec: Dict[str, Any], scale: float) -> Optional[Dict[str, Any]]:
    et = str(spec.get("type", ""))
    delta = _scaled(spec.get("delta", 0), scale)
    if delta == 0 and et != "reveal_rivals":
        return None
    out: Dict[str, Any] = {"type": et, "delta": delta}
    if et in ("player_stat",):
        out["stat"] = spec.get("stat", "trust")
        return out
    if et in ("group_mood", "group_loyalty", "support"):
        gid = action.target_group_id
        if not gid:
            return None
        out["group"] = gid
        if et == "support":
            out["kind"] = "candidate"
            if spec.get("subject") == "rival":
                rival = get_candidate(state, action.target_candidate_id) or _leading_rival(state)
                if rival is None:
                    return None
                out["subject"] = rival.name
            else:
                out["subject"] = state.player.name
        return out
    if et in ("rival_popularity", "rival_scandal", "rival_memory"):
        rival = get_candidate(state, action.target_candidate_id) or _leading_rival(state)
        if rival is None:
            return None
        out["candidate"] = rival.id
        return out
    if et == "reveal_rivals":
        out["delta"] = 1
        return out
    return out


def world_effects(state: GameState, action: ActionData, tier: str, rng: random.Random,
                  script: Dict[str, Any]) -> None:
    """Добавить в скрипт последствия смысла фразы (теги), разговора с НПС и противоречий."""
    if not ((DATA.world if DATA else {}) or {}):
        return
    effects = script.setdefault(K_EFFECTS, [])
    sign = TIER_SIGN.get(tier, 0)
    scale_map = _wcfg("tier_scale")
    scale = float(scale_map.get(tier, 1.0))
    if not getattr(action, "is_free", False):
        scale *= float(_wcfg("free_action").get("catalog_tag_scale", 0.5))
    tcfg = _wcfg("tags")
    for t in getattr(action, "tags", []) or []:
        spec = tcfg.get(t) or {}
        bucket = spec.get("success", []) if sign >= 0 else spec.get("fail", [])
        for e in bucket:
            r = _resolve_tag_effect(state, action, e, scale * (0.5 if sign == 0 else 1.0))
            if r:
                effects.append(r)
    if action.intent == "rumors" and sign > 0:
        effects.append({"type": "reveal_rivals", "delta": 1})
    # память соперника: игрок его атаковал
    if action.target_candidate_id and ("attack" in (getattr(action, "tags", []) or []) or action.intent == "attack"):
        mem = state.world.setdefault("rival_memory", {}).setdefault(action.target_candidate_id,
                                                                    {"attacked": 0, "last_move": "", "moves": 0})
        mem["attacked"] = int(mem.get("attacked", 0)) + 1
    if getattr(action, "target_npc_id", ""):
        _npc_talk(state, action, tier, rng, effects)
    _check_statement(state, action, effects, rng)
    secondary = script.setdefault("secondary", [])
    for e in effects:
        if e.get("type") in ("rival_popularity", "rival_scandal", "npc_loyalty", "reveal_rivals", "party_trust"):
            secondary.append(_world_eff_phrase(state, e))


def _world_eff_phrase(state: GameState, e: Dict[str, Any]) -> str:
    et = e.get("type")
    d = int(e.get("delta", 0))
    sd = ("+" if d > 0 else "") + str(d)
    if et in ("rival_popularity", "rival_scandal"):
        c = get_candidate(state, e.get("candidate", ""))
        what = "популярность" if et == "rival_popularity" else "скандал"
        return what + " соперника " + (c.name if c else "?") + ": " + sd
    if et == "npc_loyalty":
        n = [x for x in state.npcs if x.id == e.get("npc")]
        return "отношение " + (n[0].name if n else "?") + ": " + sd
    if et == "party_trust":
        return "доверие партий к игроку: " + sd
    if et == "reveal_rivals":
        return "получены сведения о планах соперников"
    return str(et) + ": " + sd


def _npc_talk(state: GameState, action: ActionData, tier: str, rng: random.Random,
              effects: List[Dict[str, Any]]) -> None:
    cfg = _wcfg("npc_talk")
    npc = [n for n in state.npcs if n.id == action.target_npc_id]
    if not cfg or not npc:
        return
    npc = npc[0]
    offers = cfg.get("offers") or {}
    offer_id = getattr(action, "offer", "") or "favor"
    offer = offers.get(offer_id) or {}
    traits = (cfg.get("traits") or {}).get(npc.id, {}) or {}
    trait_val = float(traits.get(str(offer.get("trait", "")), 0.3))
    mem = state.world.setdefault("npc_memory", {}).setdefault(npc.id, [])
    window = int(cfg.get("repeat_window", 4))
    repeats = sum(1 for m in mem if m.get("offer") == offer_id and state.week - int(m.get("week", 0)) <= window)
    chance = float(cfg.get("base_chance", 35)) + npc.loyalty / 2.0 + trait_val * 30.0 \
        - repeats * float(cfg.get("repeat_penalty", 15)) + 10.0 * TIER_SIGN.get(tier, 0)
    chance = max(5.0, min(95.0, chance))
    ok = rng.uniform(0, 100) < chance
    delta = int(cfg.get("success_loyalty", 8)) if ok else int(cfg.get("fail_loyalty", -6))
    effects.append({"type": "npc_loyalty", "npc": npc.id, "delta": delta})
    if ok:
        for e in (cfg.get("role_effects") or {}).get(npc.role, []) or []:
            effects.append(dict(e))
    elif offer.get("illegal"):
        for e in cfg.get("illegal_fail", []) or []:
            effects.append(dict(e))
    mem.append({"week": state.week, "offer": offer_id, "ok": ok})
    del mem[:-12]
    tpl = cfg.get("log_success") if ok else cfg.get("log_fail")
    add_log(state, _safe_format(str(tpl or "{npc}: {offer}"),
                                {"npc": npc.name, "offer": offer.get("label", offer_id), "delta": delta}))


def _check_statement(state: GameState, action: ActionData, effects: List[Dict[str, Any]], rng: random.Random) -> None:
    stance = getattr(action, "stance", "")
    issue = action.issue
    if not stance or not issue or "secret" in (getattr(action, "tags", []) or []):
        return
    cfg = _wcfg("contradiction")
    st_list = state.world.setdefault("statements", [])
    window = int(cfg.get("window_weeks", 12))
    for old in reversed(st_list):
        if old.get("issue") == issue and old.get("dir") != stance and state.week - int(old.get("week", 0)) <= window:
            for e in cfg.get("effects", []) or []:
                effects.append(dict(e))
            pub = get_publication(state, str(cfg.get("publication", "")))
            names = cfg.get("dir_names") or {}
            slots = {"publication": pub.name if pub else "Пресса", "issue": _issue_name(issue),
                     "player": state.player.name, "old_week": old.get("week", "?"),
                     "old_dir": names.get(old.get("dir"), old.get("dir")),
                     "new_dir": names.get(stance, stance)}
            push_story(state, slots["publication"], _safe_format(str(cfg.get("headline", "")), slots),
                       _safe_format(str(cfg.get("body", "")), slots), -0.6, "contradiction")
            add_log(state, "Пресса поймала на противоречии: тема «" + _issue_name(issue) + "».")
            break
    st_list.append({"week": state.week, "issue": issue, "dir": stance, "group": action.target_group_id})
    del st_list[:-40]


def _apply_world_effect(state: GameState, eff: Dict[str, Any]) -> bool:
    et = eff.get(K_EFF_TYPE)
    d = int(eff.get(K_EFF_DELTA, 0))
    if et in ("rival_popularity", "rival_scandal"):
        c = get_candidate(state, eff.get("candidate", ""))
        if c:
            if et == "rival_popularity":
                c.popularity = clamp(c.popularity + d, 0, 100)
            else:
                c.scandal = clamp(c.scandal + d, 0, 100)
        return True
    if et == "rival_memory":
        return True
    if et == "npc_loyalty":
        for n in state.npcs:
            if n.id == eff.get("npc"):
                n.loyalty = clamp(n.loyalty + d, 0, 100)
        return True
    if et == "party_trust":
        for p in state.parties:
            p.trust_to_player = clamp(p.trust_to_player + d, 0, 100)
        return True
    if et == "reveal_rivals":
        state.world["reveal_pending"] = True
        return True
    return False


def _reveal_rivals(state: GameState) -> None:
    cfg = _wcfg("rivals")
    plans = state.world.get("rival_plans") or {}
    if not plans:
        add_log(state, "Разведка: соперники пока ничего не замышляют.")
        return
    for cid, p in sorted(plans.items()):
        c = get_candidate(state, cid)
        move = ((cfg.get("moves") or {}).get(p.get("move", "")) or {}).get("label", p.get("move", ""))
        add_log(state, _safe_format(str(cfg.get("reveal_log", "{rival}: {move}")),
                                    {"rival": c.name if c else cid, "move": move}))
    state.world["revealed_week"] = state.week


def _diminish(stat: str, cur: int, delta: int) -> int:
    cfg = _wcfg("diminishing")
    if delta <= 0 or not cfg or stat not in (cfg.get("stats") or []):
        return delta
    scaled = int(round(delta * (100 - cur) / 100.0 * float(cfg.get("factor", 1.0))))
    return max(1 if cur < 100 else 0, min(delta, scaled))


def _drift_tick(state: GameState) -> None:
    cfg = _wcfg("drift")
    if not cfg or state.week % max(1, int(cfg.get("every_weeks", 1))):
        return
    pl = state.player
    if pl.awareness > int(cfg.get("awareness_floor", 20)):
        pl.awareness = clamp(pl.awareness - int(cfg.get("awareness_decay", 1)), 0, 100)
    for c in state.candidates:
        if c.popularity > int(cfg.get("rival_popularity_floor", 30)):
            c.popularity = clamp(c.popularity - int(cfg.get("rival_popularity_decay", 0)), 0, 100)
        elif c.popularity < int(cfg.get("rival_popularity_floor", 30)):
            c.popularity = clamp(c.popularity + int(cfg.get("rival_popularity_recover", 0)), 0, 100)
        c.scandal = clamp(c.scandal - int(cfg.get("rival_scandal_decay", 0)), 0, 100)
    pl.anti_awareness = clamp(pl.anti_awareness - int(cfg.get("anti_decay", 0)), 0, 100)
    neutral, step = int(cfg.get("trust_neutral", 40)), int(cfg.get("trust_step", 1))
    if pl.trust > neutral:
        pl.trust = max(neutral, pl.trust - step)
    elif pl.trust < neutral and not cfg.get("trust_only_down"):
        pl.trust = min(neutral, pl.trust + step)


def _candidate_income(state: GameState) -> None:
    cfg = _wcfg("candidate_income")
    if not cfg or state.player.prison_status != PrisonStatus.FREE:
        return
    pl = state.player
    amount = float(cfg.get("base", 0)) + float(cfg.get("per_awareness", 0)) * pl.awareness \
        + float(cfg.get("per_trust", 0)) * max(0, pl.trust - int(cfg.get("trust_floor", 0)))
    amount = max(0, int(amount))
    pl.money += amount
    state.world["last_income"] = amount


def _emergent_tick(state: GameState, rng: random.Random) -> None:
    cfg = _wcfg("emergent")
    if not cfg:
        return
    cooldowns = state.world.setdefault("event_cooldowns", {})
    hot = state.world.setdefault("hot_groups", {})
    events = sorted(cfg.get("events", []) or [], key=lambda e: -int(e.get("min_pressure", 0)))
    floor = int(cfg.get("salience_floor", 30))
    for g in state.groups:
        issue = _top_issue(g)
        if not issue:
            continue
        pressure = int(g.issues.get(issue, 0) * (100 - g.mood) / 100)
        ready = state.week - int(cooldowns.get(g.id, -99)) >= int(cfg.get("cooldown_weeks", 4))
        fired = None
        if ready and rng.random() < float(cfg.get("chance", 0.35)):
            for ev in events:
                allowed = ev.get("groups") or []
                if pressure >= int(ev.get("min_pressure", 999)) and (not allowed or g.id in allowed):
                    fired = ev
                    break
        if fired:
            eff = fired.get("effects") or {}
            g.mood = clamp(g.mood + int(eff.get("group_mood", 0)), 0, 100)
            g.issues[issue] = clamp(int(g.issues.get(issue, 0)) + int(eff.get("salience", 0)), 0, 100)
            inc = get_candidate(state, str(cfg.get("incumbent_candidate", "")))
            if inc:
                inc.popularity = clamp(inc.popularity + int(eff.get("incumbent_popularity", 0)), 0, 100)
            cooldowns[g.id] = state.week
            hot[g.id] = {"until": state.week + int(cfg.get("hot_weeks", 2)), "event": fired.get("label", ""), "issue": issue}
            pub = rng.choice(state.publications) if state.publications else None
            slots = {"group": g.name, "issue": _issue_name(issue)}
            push_story(state, pub.name if pub else "", _safe_format(str(fired.get("headline", "")), slots),
                       _safe_format(str(fired.get("body", "")), slots), -0.3, "event")
            add_log(state, _safe_format(str(cfg.get("hot_hint", "{group}: {event}")),
                                        {"group": g.name, "event": fired.get("label", "")}))
        else:
            for k in list(g.issues):
                if g.issues[k] > floor:
                    g.issues[k] = g.issues[k] - int(cfg.get("salience_decay", 1))
    for gid in list(hot):
        if int(hot[gid].get("until", 0)) < state.week:
            del hot[gid]


def _rivals_tick(state: GameState, rng: random.Random) -> bool:
    cfg = _wcfg("rivals")
    if not cfg:
        return False
    try:
        import nn_rivals
    except Exception:
        return False
    for line in nn_rivals.execute(state, cfg, rng, push_story, _issue_name):
        add_log(state, "Соперник — " + line)
    nn_rivals.plan(state, cfg, rng)
    if state.world.pop("reveal_pending", False):
        _reveal_rivals(state)
    return True


def snapshot(state: GameState) -> Dict[str, Any]:
    pl = state.player
    return {"Узнаваемость": pl.awareness, "Доверие": pl.trust, "Антирейтинг": pl.anti_awareness,
            "Деньги": pl.money, "Угроза": pl.threat, "Улики": pl.evidence,
            "rivals": {c.name: c.popularity - c.scandal for c in state.candidates},
            "news": state.next_archive_no}


def week_summary(before: Dict[str, Any], state: GameState) -> str:
    after = snapshot(state)
    parts: List[str] = []
    for k, v in before.items():
        if k in ("rivals", "news"):
            continue
        d = int(after[k]) - int(v)
        if d:
            parts.append(k + " " + ("+" if d > 0 else "") + str(d))
    rv: List[str] = []
    for name, v in (before.get("rivals") or {}).items():
        d = int(after["rivals"].get(name, v)) - int(v)
        if d:
            rv.append(name + " " + ("+" if d > 0 else "") + str(d))
    text = "Итоги недели: " + (", ".join(parts) if parts else "без изменений")
    if rv:
        text += ". Соперники: " + ", ".join(rv)
    hot = _hot_groups(state)
    if hot:
        names = [_group_name(state, gid) + " (" + str(v.get("event", "")) + ")" for gid, v in sorted(hot.items())]
        text += ". Горячие точки: " + ", ".join(names)
    return text + "."


def target_label(state: GameState, target: str) -> str:
    if not target:
        return ""
    g = get_group(state, target)
    if g is not None:
        return _group_name(state, target)
    c = get_candidate(state, target)
    if c is not None:
        return c.name
    for n in state.npcs:
        if n.id == target:
            return n.name
    party = get_party(state, target)
    if party is not None:
        return party.name
    return _issue_name(target)


def plan_lines(state: GameState) -> List[str]:
    """Строки плана недели для UI: название, цель, шанс, цена."""
    out: List[str] = []
    for i, qa in enumerate(state.week_actions, 1):
        action = ACTIONS.get(str(qa.get("action_id", "")))
        title = action.title if action else str(qa.get("action_id", ""))
        raw = str(qa.get("raw", "") or "")
        if action is not None and action.id == _free_id() and raw:
            short = raw if len(raw) <= 48 else raw[:48].rsplit(" ", 1)[0] + "…"
            title = "Своё: «" + short + "»"
        bits = [title]
        tgt = target_label(state, str(qa.get("target", "") or ""))
        if tgt:
            bits.append("→ " + tgt)
        if qa.get("issue"):
            bits.append("тема: " + _issue_name(str(qa.get("issue"))))
        tail = "шанс ~" + str(qa.get("chance", "?")) + "%, цена " + str(qa.get("cost_paid", 0))
        if qa.get("delayed"):
            tail += ", отложено"
        out.append(str(i) + ". " + " ".join(bits) + " (" + tail + ")")
    return out


def cancel_action(state: GameState, idx: int) -> str:
    if idx < 1 or idx > len(state.week_actions):
        return "Нет действия с номером " + str(idx) + ". Сейчас в плане: " + str(len(state.week_actions)) + "."
    qa = state.week_actions.pop(idx - 1)
    refund = int(qa.get("cost_paid", 0) or 0)
    state.player.money += refund
    state.actions_this_week = max(0, state.actions_this_week - 1)
    action = ACTIONS.get(str(qa.get("action_id", "")))
    return "Отменено: " + (action.title if action else str(qa.get("action_id"))) + ". Возврат " + str(refund) + "."


def world_report(state: GameState) -> List[str]:
    """Экран «Город»: соперники, их последние ходы и разведанные планы, горячие точки, НПС."""
    cfg = _wcfg("rivals")
    moves = cfg.get("moves") or {}
    mem = state.world.get("rival_memory") or {}
    lines: List[str] = ["Соперники (рейтинг − скандал):"]
    for c in sorted(state.candidates, key=lambda x: -(x.popularity - x.scandal)):
        m = mem.get(c.id) or {}
        last = str(m.get("last_move", "") or "")
        last_lbl = str((moves.get(last) or {}).get("label", last)) if last else "—"
        lines.append("  · " + c.name + ": поп. " + str(c.popularity) + ", скандал " + str(c.scandal) +
                     " | последний ход: " + last_lbl + " | атак на тебя: " + str(int(m.get("attacked", 0) or 0)))
    rw = state.world.get("revealed_week")
    plans = state.world.get("rival_plans") or {}
    lines.append("")
    if rw is not None and int(rw) >= state.week - 1 and plans:
        lines.append("Разведанные планы (неделя " + str(rw) + "):")
        for cid, p in sorted(plans.items()):
            c = get_candidate(state, cid)
            lbl = str((moves.get(p.get("move", "")) or {}).get("label", p.get("move", "")))
            grp = _group_name(state, p.get("group", "")) if p.get("group") else ""
            lines.append("  · " + (c.name if c else cid) + ": " + lbl + (" (" + grp + ")" if grp else ""))
    else:
        lines.append("Планы соперников неизвестны. Подсказка: «разведать планы Ложкина».")
    lines.append("")
    hot = state.world.get("hot_groups") or {}
    lines.append("Горячие точки:")
    if not hot:
        lines.append("  спокойно")
    for gid, v in sorted(hot.items()):
        lines.append("  · " + _group_name(state, gid) + ": " + str(v.get("event", "")) +
                     " (тема: " + _issue_name(str(v.get("issue", ""))) + ", до нед. " + str(v.get("until", "?")) + ")")
    lines.append("")
    lines.append("Группы (настроение / лояльность / главная тема):")
    for g in state.groups:
        lines.append("  · " + _group_name(state, g.id) + ": " + str(g.mood) + " / " + str(g.loyalty) +
                     " / " + (_issue_name(_top_issue(g)) or "—"))
    lines.append("")
    lines.append("Люди города (лояльность к тебе):")
    nmem = state.world.get("npc_memory") or {}
    for n in state.npcs:
        last = (nmem.get(n.id) or [])
        tail = ""
        if last and isinstance(last[-1], dict):
            off = str(last[-1].get("offer", ""))
            lbl = str(((_wcfg("npc_talk").get("offers") or {}).get(off) or {}).get("label", off))
            tail = " | нед. " + str(last[-1].get("week", "?")) + ": " + lbl + (" — согласился" if last[-1].get("ok") else " — отказал")
        lines.append("  · " + n.name + " (" + n.role + "): " + str(n.loyalty) + tail)
    inc = state.world.get("last_income")
    if inc is not None:
        lines.append("")
        lines.append("Пожертвования сторонников за прошлую неделю: +" + str(inc))
    return lines


# ================= двухфазный конец недели с ревизией =================
def _effective_action(state: GameState, qa: Dict[str, Any]) -> Optional[ActionData]:
    base = ACTIONS.get(qa.get("action_id", ""))
    if not base:
        return None
    target = qa.get("target", "")
    intent = qa.get("intent", "")
    issue = qa.get("issue", "")
    if issue:
        base = _clone_action(base, issue=issue)
    if not target:
        return _apply_world_meta(state, base, qa)
    if intent == "bill":
        base = _clone_action(base, issue=target)
    elif intent == "party":
        base = _clone_action(base, target_group_id=target, issue=target)
    # цель определяем по тому, что это за сущность, а не по списку интентов
    # (раньше митинг/обход/сборы теряли группу и били по первой группе в списке)
    elif get_group(state, target) is not None:
        base = _clone_action(base, target_group_id=target)
    elif intent == "attack" or any(c.id == target for c in state.candidates):
        base = _clone_action(base, target_candidate_id=target)
    return _apply_world_meta(state, base, qa)


def begin_week_end(state: GameState) -> List[Dict[str, Any]]:
    global _PENDING_REVIEW
    rng = get_week_rng(state, 0)
    review: List[Dict[str, Any]] = []
    arrested_allowed = set(str(x) for x in (_bal(K_BAL_ARRESTED_ALLOWED) or []))
    for idx, qa in enumerate(state.week_actions):
        action = _effective_action(state, qa)
        if not action:
            continue
        if state.player.prison_status in (PrisonStatus.ARRESTED, PrisonStatus.PRISON) and action.intent not in arrested_allowed:
            state.player.money += qa["cost_paid"]
            cancel_script = {"primary": _svc("arrested_cancel"), K_EFFECTS: [], "reactors": [],
                             "tone": -0.2, "secondary": [], "plausibility": 1.0, "delayed": [],
                             "tier_distribution": {}, "tone_vector": {}, "reason_key": "context"}
            review.append({"index": idx, "action_id": qa["action_id"], "title": action.title,
                           "tier": "cancelled", "script": cancel_script, "text": None,
                           "verdict": None, "correction": ""})
            continue
        executed, success, text, script, clipping = resolve_action(state, action, rng)
        review.append({"index": idx, "action_id": qa["action_id"], "title": action.title,
                       "tier": "resolved", "script": script, "text": clipping,
                       "verdict": None, "correction": "", "executed": executed, "success": success})
    for law in state.custom_laws:
        if law["status"] == "enacted" and law.get("enacted_week", 0) >= state.week - 2:
            forecast = law.get("forecast_script") or analyze_law(state, law, rng)
            law["forecast_script"] = forecast
            actual = drift_script(forecast, rng)
            law["actual_scripts"].append(actual)
            pub = get_publication(state, "")
            payload = {"tone": actual.get("tone", 0.0), "reason": actual.get("primary", law["title"]),
                       "bill": law["title"], "publication": pub.name if pub else "",
                       "title": "закон " + str(law["title"]), "tier_word": "закон",
                       "reactors": actual.get("reactors", []), "deltas_words": _effects_to_words(state, actual),
                       "tier_distribution": actual.get("tier_distribution", {}),
                       "tone_vector": actual.get("tone_vector", {}), "issue": "", "week": state.week,
                       "level": getattr(state.village, "level", "city"),
                       "population": getattr(state.village, "population", 0)}
            clipping = make_clipping(state, payload, rng)
            review.append({"index": len(review), "action_id": law["id"], "title": "Закон: " + str(law["title"]),
                           "tier": "law", "script": actual, "text": clipping, "verdict": None, "correction": ""})
    _PENDING_REVIEW = review
    return review


def finish_week(state: GameState, verdicts: List[Dict[str, Any]], rng_unused: Optional[random.Random] = None) -> None:
    global _PENDING_REVIEW
    rng = get_week_rng(state, 50)
    by_index = {v.get("index"): v for v in verdicts}
    for item in _PENDING_REVIEW:
        v = by_index.get(item["index"], {})
        verdict = v.get("verdict", "yes")
        correction = v.get("correction", "")
        script = item["script"]
        if verdict == "no" and correction:
            patched = None
            if _analyzer_enabled():
                try:
                    import nn_analyzer
                    patched, _applied = nn_analyzer.patch_script(script, correction, state)
                except Exception:
                    patched = None
            if patched is None:
                patched = json.loads(json.dumps(script))
                patched["primary"] = str(patched.get("primary", "")) + " " + _svc("player_override_prefix", correction=correction)
                patched["player_override"] = True
            script = patched
        # эффекты применяются РОВНО ОДИН РАЗ здесь, после учёта правки игрока
        _apply_script_effects(state, script)
        if item.get("text"):
            item["text"]["body"] = (str(item["text"].get("body", "")) + " " + str(script.get("primary", ""))).strip()
        log_analyzer_judgment({"week": state.week, "seed": state.seed,
                               "week_seed": (state.week_seeds[-1] if state.week_seeds else None),
                               "action_id": item["action_id"], "tier": item["tier"],
                               "script": script, "verdict": verdict, "correction": correction,
                               "rng_snapshot": rng_state_to_json(rng),
                               "payload_snapshot": {"title": item.get("title", "")}})
    _PENDING_REVIEW = []
    state.week_actions = []
    info = budget_info(state)
    state.treasury += info["net"]
    for promise in list(state.promises):
        if promise["status"] == "active":
            promise["progress"] = clamp(promise["progress"] + 25, 0, 100)
            if state.week >= promise["deadline_week"]:
                promise["status"] = "kept" if promise["progress"] >= 100 else "broken"
                if promise["status"] == "broken":
                    g = get_group(state, promise["group_id"])
                    if g:
                        g.loyalty = clamp(g.loyalty - 8, 0, 100)
                    state.player.trust = clamp(state.player.trust - 4, 0, 100)
    tick_bills(state, rng)
    for fact in _week_facts(state, rng):
        make_news_item(state, fact.payload, rng)
    _npc_moves(state, rng)
    _candidate_income(state)
    _drift_tick(state)
    _emergent_tick(state, rng)
    if not _rivals_tick(state, rng):
        _candidate_moves(state, rng)
    _party_reactions(state, rng)
    _prison_tick(state, rng)
    if state.week >= state.next_election_week and not state.is_game_over:
        _run_elections(state, rng)
    state.week += 1
    state.current_week = state.week
    state.actions_this_week = 0
    draw_next_week_seed(state)
    add_log(state, "Неделя завершена. Казна " + str(state.treasury) + ".")
    if state.player.health <= 0 and not state.is_game_over:
        _player_death(state)


# ================= каталог действий (ТОЛЬКО из JSON; fallback-каталога в коде НЕТ) =================
def _build_actions() -> Dict[str, ActionData]:
    raw = list((DATA.actions if DATA else []) or [])
    if not raw:
        raise DataError("actions/actions.json: каталог действий пуст — играть нечем (вшитого fallback нет).")
    out: Dict[str, ActionData] = {}
    for a in raw:
        act = ActionData(
            id=str(a.get(K_ACTION_ID, "")), title=str(a.get(K_TITLE, "")),
            description=str(a.get(K_DESC, "")), intent=str(a.get(K_INTENT, "")),
            issue=str(a.get(K_ISSUE, "")),
            target_candidate_id=str(a.get(K_TARGET_CAND, "")),
            target_group_id=str(a.get(K_TARGET_GROUP, "")),
            delayed=bool(a.get(K_DELAYED, False)), cost=int(a.get(K_COST, 0)),
        )
        setattr(act, "skill", str(a.get(K_SKILL, "")))
        setattr(act, "difficulty", int(a.get(K_DIFFICULTY, 0) or 0))
        setattr(act, "effects", list(a.get(K_EFFECTS, []) or []))
        setattr(act, "secret", bool(a.get(K_SECRET, False)))
        setattr(act, "illegality", float(a.get(K_ILLEGALITY, 0.0) or 0.0))
        setattr(act, "risk", int(a.get(K_RISK, 0) or 0))
        setattr(act, "category", str(a.get(K_CATEGORY, "")))
        if not act.id:
            raise DataError("actions/actions.json: запись без обязательного поля 'id'.")
        out[act.id] = act
    return out


def refresh_actions() -> None:
    global ACTIONS
    ACTIONS = _build_actions()