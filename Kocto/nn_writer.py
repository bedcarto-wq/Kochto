from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import models

LEXICONS_PATH = models.DATA_DIR / "nn" / "lexicons.json"
WEIGHTS_PATH = models.DATA_DIR / "nn" / "weights.json"

# enum-контракты (структура плана, НЕ контент)
ROLES: Tuple[str, ...] = ("lead", "fact", "eval", "consequence", "reaction", "quote",
                          "context", "contrast", "forecast", "detail", "coda")
TIERS: Tuple[str, ...] = ("great", "solid", "complication", "minor", "major", "catastrophe")

# имена полей JSON (контракт схемы, НЕ контент)
K_SCHEMA = "schema_version"
K_REGISTERS = "registers"
K_EVAL_FEM = "eval_fem"
K_OPENERS = "openers"
K_QUOTES = "quotes"
K_CONNECTORS = "connectors"
K_SUBSTITUTES = "substitutes"
K_SUBSTITUTES_EXT = "substitutes_extended"
K_CONSEQUENCES = "consequences"
K_REACTIONS = "reactions"
K_ROLE_PHRASES = "role_phrases"
K_VECTOR_PHRASES = "vector_phrases"
K_TIER_EVAL = "tier_eval"
K_TONE_EVAL = "tone_eval"
K_REASON_PHRASES = "reason_phrases"
K_REACTOR_TEMPLATES = "reactor_templates"
K_CTX = "context_phrases"
K_CONTRAST = "contrast_phrases"
K_FORECAST = "forecast_phrases"
K_DETAIL = "detail_phrases"
K_INTRO = "intro_phrases"
K_QUESTION = "question_forms"
K_EXCLAIM = "exclamation_forms"
K_SENT_STRUCT = "sentence_structures"
K_CONN = "connectors"
K_INTRO_CONSTR = "intro_constructions"
K_QUOTE_SRC = "quote_sources"
K_THEMATIC = "thematic_clusters"
K_EMOTION = "emotion_by_tone"
K_CLAUSES = "clauses"
K_PLAYER_NOTE = "player_correction_template"

K_W_ROLE_TRANS = "role_transitions"
K_W_REG_WEIGHTS = "register_weights"
K_W_VAR_WEIGHTS = "variation_weights"
K_W_OVERLAP = "overlap_threshold"
K_W_MAX_ROLES = "max_roles_by_importance"
K_W_QUOTE = "quote_chance"
K_W_INTRO = "intro_chance"
K_W_ATTEMPTS = "max_attempts"
K_W_CTX = "context_chance"
K_W_CONTRAST = "contrast_chance"
K_W_FORECAST = "forecast_chance"
K_W_DETAIL = "detail_chance"

_SESSION_HISTORY: List[str] = []
_FREE = False


def available() -> bool:
    return True


def set_free_generator(flag: bool) -> None:
    global _FREE
    _FREE = bool(flag)


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise models.DataError("nn_writer: отсутствует файл " + str(path) +
                               " при включённом enabled_writer. Вшитых дефолтов нет — создай файл.")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise models.DataError("nn_writer: повреждён " + str(path) + " (" + str(exc) + ").")


def _need_map(d: Any, where: str) -> Dict[str, Any]:
    if not isinstance(d, dict):
        raise models.DataError("nn_writer." + where + ": ожидался объект JSON.")
    return d


def _need_list(d: Any, where: str) -> List[Any]:
    if not isinstance(d, list):
        raise models.DataError("nn_writer." + where + ": ожидался массив JSON.")
    return d


def _need_keys(obj: Dict[str, Any], keys: Tuple[str, ...], where: str) -> None:
    missing = [k for k in keys if k not in obj]
    if missing:
        raise models.DataError("nn_writer." + where + ": нет обязательных ключей: " + ", ".join(missing) + ".")


def _lexicons() -> Dict[str, Any]:
    raw = _load_json(LEXICONS_PATH)
    d = _need_map(raw, "lexicons")
    _need_keys(d, (K_SCHEMA, K_REGISTERS, K_SUBSTITUTES, K_CONSEQUENCES, K_REACTIONS,
                   K_ROLE_PHRASES, K_VECTOR_PHRASES, K_REASON_PHRASES, K_REACTOR_TEMPLATES), "lexicons")
    regs = _need_map(d[K_REGISTERS], "lexicons.registers")
    if not regs:
        raise models.DataError("nn_writer.lexicons.registers: пусто — нечем фразизовать тон.")
    for rname, rval in regs.items():
        rm = _need_map(rval, "lexicons.registers." + str(rname))
        _need_keys(rm, (K_EVAL_FEM, K_OPENERS, K_QUOTES, K_CONNECTORS), "lexicons.registers." + str(rname))
        ef = _need_map(rm[K_EVAL_FEM], "lexicons.registers." + str(rname) + ".eval_fem")
        _need_keys(ef, ("pos", "neg", "neu"), "lexicons.registers." + str(rname) + ".eval_fem")
        for lk in (K_OPENERS, K_QUOTES, K_CONNECTORS):
            _need_list(rm[lk], "lexicons.registers." + str(rname) + "." + lk)
    rp = _need_map(d[K_ROLE_PHRASES], "lexicons.role_phrases")
    miss_roles = [r for r in ROLES if r not in rp]
    if miss_roles:
        raise models.DataError("nn_writer.lexicons.role_phrases: нет фраз для ролей: " + ", ".join(miss_roles) + ".")
    for rname in ROLES:
        _need_list(rp[rname], "lexicons.role_phrases." + str(rname))
    vp = _need_map(d[K_VECTOR_PHRASES], "lexicons.vector_phrases")
    _need_keys(vp, (K_TIER_EVAL, K_TONE_EVAL), "lexicons.vector_phrases")
    te = _need_map(vp[K_TIER_EVAL], "lexicons.vector_phrases.tier_eval")
    miss_tiers = [t for t in TIERS if t not in te]
    if miss_tiers:
        raise models.DataError("nn_writer.lexicons.vector_phrases.tier_eval: нет оценок для тиров: "
                               + ", ".join(miss_tiers) + ".")
    _need_map(vp[K_TONE_EVAL], "lexicons.vector_phrases.tone_eval")
    rph = _need_map(d[K_REASON_PHRASES], "lexicons.reason_phrases")
    if "default" not in rph:
        raise models.DataError("nn_writer.lexicons.reason_phrases: нет обязательного ключа 'default'.")
    rt = _need_map(d[K_REACTOR_TEMPLATES], "lexicons.reactor_templates")
    if "list" not in rt:
        raise models.DataError("nn_writer.lexicons.reactor_templates: нет обязательного ключа 'list'.")
    _need_list(d[K_CONSEQUENCES], "lexicons.consequences")
    _need_list(d[K_REACTIONS], "lexicons.reactions")
    _need_map(d[K_SUBSTITUTES], "lexicons.substitutes")
    return d


def _weights() -> Dict[str, Any]:
    raw = _load_json(WEIGHTS_PATH)
    d = _need_map(raw, "weights")
    writer = d.get("writer")
    if writer is None:
        raise models.DataError("nn_writer: в weights.json нет секции 'writer' при включённом enabled_writer.")
    w = _need_map(writer, "weights.writer")
    _need_keys(w, (K_W_ROLE_TRANS, K_W_REG_WEIGHTS, K_W_VAR_WEIGHTS, K_W_OVERLAP,
                   K_W_MAX_ROLES, K_W_QUOTE, K_W_INTRO, K_W_ATTEMPTS), "weights.writer")
    rt = _need_map(w[K_W_ROLE_TRANS], "weights.writer.role_transitions")
    for rname in ROLES:
        if rname in rt:
            lst = _need_list(rt[rname], "weights.writer.role_transitions." + str(rname))
            for item in lst:
                if not (isinstance(item, (list, tuple)) and len(item) == 2):
                    raise models.DataError("weights.writer.role_transitions." + str(rname) +
                                           ": элемент должен быть [next_role, weight].")
    _need_map(w[K_W_REG_WEIGHTS], "weights.writer.register_weights")
    _need_map(w[K_W_VAR_WEIGHTS], "weights.writer.variation_weights")
    ov = float(w[K_W_OVERLAP])
    if not (0.0 < ov <= 1.0):
        raise models.DataError("weights.writer.overlap_threshold: должно быть в (0,1], получено " + str(ov) + ".")
    mr = _need_map(w[K_W_MAX_ROLES], "weights.writer.max_roles_by_importance")
    if not mr:
        raise models.DataError("weights.writer.max_roles_by_importance: пусто.")
    if int(w[K_W_ATTEMPTS]) < 1:
        raise models.DataError("weights.writer.max_attempts: должно быть >= 1.")
    return w


# ================= n-gram / сессионная история =================
def _ngrams(text: str, n: int = 3) -> set:
    words = text.lower().split()
    if len(words) < n:
        return {text.lower()}
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def _overlap_ratio(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _remember_session(text: str) -> None:
    _SESSION_HISTORY.append(text)
    while len(_SESSION_HISTORY) > 60:
        _SESSION_HISTORY.pop(0)


def _too_similar_session(text: str, threshold: float) -> bool:
    cand = _ngrams(text)
    for old in _SESSION_HISTORY:
        if _overlap_ratio(cand, _ngrams(old)) >= threshold:
            return True
    return False


# ================= выбор регистра / план ролей =================
def _pick_register(rng: random.Random, tone: float, w: Dict[str, Any]) -> str:
    rw = w[K_W_REG_WEIGHTS]
    pool: List[Tuple[str, float]] = []
    for reg, base in rw.items():
        adj = float(base)
        if reg == "alarmist" and abs(tone) > 0.4:
            adj *= 1.6
        if reg == "official" and abs(tone) <= 0.2:
            adj *= 1.3
        if reg == "emotional" and abs(tone) > 0.5:
            adj *= 1.4
        if reg == "ironic" and tone < -0.3:
            adj *= 1.2
        pool.append((reg, adj))
    total = sum(v for _, v in pool) or 1.0
    r = rng.uniform(0, total)
    acc = 0.0
    for reg, v in pool:
        acc += v
        if r <= acc:
            return reg
    return pool[0][0]


def _plan_roles(rng: random.Random, importance: float, w: Dict[str, Any]) -> List[str]:
    mr = w[K_W_MAX_ROLES]
    target_len = 3
    for thr in sorted((float(k) for k in mr.keys()), reverse=True):
        if importance >= thr:
            target_len = int(mr[str(thr)] if str(thr) in mr else mr[_key_for(mr, thr)])
            break
    trans = w[K_W_ROLE_TRANS]
    chain = ["lead"]
    current = "lead"
    guard = 0
    while len(chain) < target_len and guard < 32:
        guard += 1
        opts = trans.get(current)
        if not opts:
            break
        pairs: List[Tuple[str, float]] = []
        for item in opts:
            pairs.append((str(item[0]), float(item[1])))
        total = sum(v for _, v in pairs) or 1.0
        r = rng.uniform(0, total)
        acc = 0.0
        chosen = pairs[0][0]
        for nxt, v in pairs:
            acc += v
            if r <= acc:
                chosen = nxt
                break
        if chosen in chain:
            break
        chain.append(chosen)
        current = chosen
    if chain[-1] != "coda":
        chain.append("coda")
    return chain


def _key_for(d: Dict[str, Any], val: float) -> str:
    for k in d.keys():
        try:
            if abs(float(k) - val) < 1e-9:
                return str(k)
        except (TypeError, ValueError):
            continue
    return next(iter(d.keys()))


# ================= когезия =================
class _Cohesion:
    def __init__(self, payload: Dict[str, Any], subs: Dict[str, str], subs_ext: Dict[str, List[str]]):
        self.payload = payload
        self.subs = subs
        self.subs_ext = subs_ext
        self.used: Dict[str, bool] = {}
        self.sub_used: Dict[str, int] = {}

    def mention(self, key: str) -> str:
        name = str(self.payload.get(key, "")) or str(self.subs.get(key, key))
        if not self.used.get(key):
            self.used[key] = True
            return name
        ext = self.subs_ext.get(key) or [name]
        idx = self.sub_used.get(key, 0) % len(ext)
        self.sub_used[key] = idx + 1
        return str(ext[idx])


# ================= безопасное форматирование (без KeyError) =================
def _fmt(template: str, slots: Dict[str, Any]) -> str:
    try:
        return template.format(**slots)
    except (KeyError, IndexError, ValueError):
        out = template
        for k, v in slots.items():
            out = out.replace("{" + str(k) + "}", str(v))
        return out


def _opt_list(lex: Dict[str, Any], key: str) -> List[str]:
    val = lex.get(key)
    if isinstance(val, list) and val:
        return [str(x) for x in val]
    return []


def _opt_map(lex: Dict[str, Any], key: str) -> Dict[str, Any]:
    val = lex.get(key)
    return val if isinstance(val, dict) else {}


# ================= фразизация векторов =================
def _tone_bucket(polarity: float, intensity: float) -> str:
    pol = "pos" if polarity > 0.15 else ("neg" if polarity < -0.15 else "neu")
    if intensity >= 0.66:
        lvl = "high"
    elif intensity >= 0.33:
        lvl = "mid"
    else:
        lvl = "low"
    return pol + ":" + lvl


def _vector_eval(lex: Dict[str, Any], tier_dist: Dict[str, float], tone_vec: Dict[str, float]) -> str:
    vp = _opt_map(lex, K_VECTOR_PHRASES)
    te = _opt_map(vp, K_TIER_EVAL)
    dominant = "complication"
    best = -1.0
    for t in TIERS:
        p = float(tier_dist.get(t, 0.0))
        if p > best:
            best = p
            dominant = t
    second = ""
    second_p = -1.0
    for t in TIERS:
        if t == dominant:
            continue
        p = float(tier_dist.get(t, 0.0))
        if p > second_p:
            second_p = p
            second = t
    base = str(te.get(dominant, te.get("default", "")))
    tone_eval = _opt_map(vp, K_TONE_EVAL)
    bucket = _tone_bucket(float(tone_vec.get("polarity", 0.0)), float(tone_vec.get("intensity", 0.0)))
    tone_word = str(tone_eval.get(bucket, tone_eval.get("default", "")))
    mix = ""
    if second and second_p >= 0.2:
        mix_tmpl = str(te.get("mix", "{dominant} с оттенком {second}"))
        mix = _fmt(mix_tmpl, {"dominant": dominant, "second": second})
    parts = [p for p in (base, tone_word, mix) if p]
    return " ".join(parts)


def _reason_phrase(lex: Dict[str, Any], reason_key: str) -> str:
    rp = _opt_map(lex, K_REASON_PHRASES)
    return str(rp.get(reason_key, rp.get("default", "")))


def _reactor_phrase(lex: Dict[str, Any], reactors: List[str]) -> str:
    rt = _opt_map(lex, K_REACTOR_TEMPLATES)
    names = ", ".join(str(x) for x in reactors if x)
    if not names:
        return ""
    return _fmt(str(rt.get("list", "{names}")), {"names": names})


# ================= сборка роли =================
def _realize_role(role: str, lex: Dict[str, Any], register: str, polarity: str,
                  rng: random.Random, slots: Dict[str, Any], w: Dict[str, Any]) -> str:
    regs = _opt_map(lex, K_REGISTERS)
    reg = _opt_map(regs, register) or _opt_map(regs, next(iter(regs.keys()), "official"))
    eval_fem = _opt_map(reg, K_EVAL_FEM)
    openers = reg.get(K_OPENERS) or [""]
    quotes = reg.get(K_QUOTES) or [""]
    connectors = reg.get(K_CONNECTORS) or [""]
    rp = _opt_map(lex, K_ROLE_PHRASES)
    templates = rp.get(role) or ["{player} — {issue}"]

    local = dict(slots)
    local["eval_word"] = rng.choice(eval_fem.get(polarity) or eval_fem.get("neu") or [""])
    local["opening"] = rng.choice(openers)
    local["quote_word"] = rng.choice(quotes)
    local["connector_word"] = rng.choice(connectors)
    cons = _opt_list(lex, K_CONSEQUENCES)
    reac = _opt_list(lex, K_REACTIONS)
    ctx = _opt_list(lex, K_CTX)
    con = _opt_list(lex, K_CONTRAST)
    fore = _opt_list(lex, K_FORECAST)
    det = _opt_list(lex, K_DETAIL)
    local["consequence_word"] = rng.choice(cons) if cons else ""
    local["reaction_word"] = rng.choice(reac) if reac else ""
    local["context_word"] = rng.choice(ctx) if ctx else ""
    local["contrast_word"] = rng.choice(con) if con else ""
    local["forecast_word"] = rng.choice(fore) if fore else ""
    local["detail_word"] = rng.choice(det) if det else ""
    local["vector_eval_word"] = str(slots.get("vector_eval", ""))
    local["reason_word"] = str(slots.get("reason_phrase", ""))
    local["reactor_word"] = str(slots.get("reactor_phrase", ""))
    local["deltas_word"] = "; ".join(str(x) for x in (slots.get("deltas_words") or []))

    tmpl = str(rng.choice(templates))
    return _fmt(tmpl, local)


# ================= заголовок =================
def _headline(rng: random.Random, lex: Dict[str, Any], slots: Dict[str, Any],
              w: Dict[str, Any], tone: float) -> str:
    vw = w[K_W_VAR_WEIGHTS]
    styles: List[Tuple[str, float, str]] = []
    statement = str(vw.get("statement", 1.0))
    exclaim = str(vw.get("exclamation", 0.5))
    compound = str(vw.get("compound", 0.8))
    question = str(vw.get("question", 0.4))
    qforms = _opt_list(lex, K_QUESTION)
    eforms = _opt_list(lex, K_EXCLAIM)
    base_head = "{player}: {issue}"
    styles.append(("statement", float(statement), base_head))
    if eforms:
        styles.append(("exclamation", float(exclaim), rng.choice(eforms)))
    styles.append(("compound", float(compound), "{player} — {group}"))
    if qforms:
        styles.append(("question", float(question), rng.choice(qforms)))
    if tone < -0.4:
        boosted: List[Tuple[str, float, str]] = []
        for s, wt, t in styles:
            boosted.append((s, wt * (1.4 if s in ("exclamation", "question") else 1.0), t))
        styles = boosted
    total = sum(wt for _, wt, _ in styles) or 1.0
    r = rng.uniform(0, total)
    acc = 0.0
    chosen = styles[0][2]
    for _, wt, t in styles:
        acc += wt
        if r <= acc:
            chosen = t
            break
    head = _fmt(chosen, slots)
    if len(head) < 8:
        head = _fmt(base_head, slots)
    if len(head) > 90:
        head = head[:87] + "..."
    return head


# ================= вставка цитаты / вводной =================
def _maybe_intro(sentence: str, rng: random.Random, lex: Dict[str, Any], w: Dict[str, Any]) -> str:
    if rng.random() >= float(w[K_W_INTRO]):
        return sentence
    intros = _opt_list(lex, K_INTRO)
    if not intros:
        return sentence
    return _fmt("{intro}, {sentence}", {"intro": rng.choice(intros), "sentence": sentence.lower()})


def _maybe_quote(sentences: List[str], rng: random.Random, lex: Dict[str, Any],
                 w: Dict[str, Any], slots: Dict[str, Any]) -> List[str]:
    if rng.random() >= float(w[K_W_QUOTE]):
        return sentences
    regs = _opt_map(lex, K_REGISTERS)
    reg = _opt_map(regs, slots.get("register", "official"))
    quotes = reg.get(K_QUOTES) or []
    if not quotes:
        return sentences
    qsrc = _opt_list(lex, K_QUOTE_SRC)
    src = rng.choice(qsrc) if qsrc else "{npc}"
    quote = rng.choice(quotes)
    line = _fmt("«{quote}» — {source}", {"quote": quote, "source": _fmt(src, slots)})
    pos = rng.randint(1, len(sentences)) if sentences else 0
    sentences.insert(pos, line)
    return sentences


# ================= мягкая внутренняя валидация (для ретраев) =================
def _soft_valid(text: str) -> bool:
    body = text
    words = len(body.split())
    sentences = body.count(".")
    return words >= 15 and 2 <= sentences <= 7


# ================= сборка =================
def _assemble(payload: Dict[str, Any], rng: random.Random, importance: float,
              kind: str) -> Optional[Dict[str, str]]:
    lex = _lexicons()
    w = _weights()
    threshold = float(w[K_W_OVERLAP])
    attempts = int(w[K_W_ATTEMPTS])
    tone = float(payload.get("tone", 0.0))
    polarity = "pos" if tone > 0.15 else ("neg" if tone < -0.15 else "neu")
    tier_dist = payload.get("tier_distribution") or {}
    tone_vec = payload.get("tone_vector") or {"polarity": tone, "intensity": abs(tone)}
    reason_key = str(payload.get("reason_key", "luck"))
    reactors = payload.get("reactors") or []
    deltas = payload.get("deltas_words") or []

    subs = _opt_map(lex, K_SUBSTITUTES)
    subs_ext = _opt_map(lex, K_SUBSTITUTES_EXT)
    coh = _Cohesion(payload, subs, subs_ext)

    base_slots = {
        "player": coh.mention("player"),
        "group": coh.mention("group"),
        "party": coh.mention("party"),
        "publication": coh.mention("publication"),
        "npc": coh.mention("npc"),
        "candidate": coh.mention("candidate"),
        "village": str(payload.get("village", "")),
        "issue": str(payload.get("issue", "")),
        "bill": str(payload.get("bill", "")),
        "promise": str(payload.get("promise", "")),
        "title": str(payload.get("title", payload.get("action_title", ""))),
        "tier_word": str(payload.get("tier_word", "")),
        "week": str(payload.get("week", "")),
        "level": str(payload.get("level", "")),
        "population": str(payload.get("population", "")),
        "vector_eval": _vector_eval(lex, tier_dist, tone_vec),
        "reason_phrase": _reason_phrase(lex, reason_key),
        "reactor_phrase": _reactor_phrase(lex, reactors),
        "deltas_words": deltas,
        "player_note": str(payload.get("player_correction", "")),
    }

    for _attempt in range(attempts):
        register = _pick_register(rng, tone, w)
        slots = dict(base_slots)
        slots["register"] = register
        roles = _plan_roles(rng, importance, w)
        sentences: List[str] = []
        for role in roles:
            sent = _realize_role(role, lex, register, polarity, rng, slots, w)
            if role in ("lead", "fact", "eval"):
                sent = _maybe_intro(sent, rng, lex, w)
            if sent.strip():
                sentences.append(sent.strip())
        sentences = _maybe_quote(sentences, rng, lex, w, slots)
        if not sentences:
            continue
        lead = sentences[0]
        body = " ".join(sentences[1:]) if len(sentences) > 1 else lead
        headline = _headline(rng, lex, slots, w, tone)
        full = headline + " " + lead + " " + body
        if _too_similar_session(full, threshold):
            continue
        if not _soft_valid(body):
            continue
        _remember_session(full)
        reason = str(payload.get("reason", "")) or slots["reason_phrase"]
        if kind == "news":
            return {"headline": headline, "lead": "", "body": (lead + " " + body).strip(), "reason": reason}
        return {"headline": headline, "lead": lead, "body": body, "reason": reason}
    return None


# ================= публичные входы (контракты systems.py) =================
def compose_clipping(report: Dict[str, Any], rng: random.Random,
                     templates: Dict[str, Any]) -> Optional[Dict[str, str]]:
    payload = dict(report or {})
    importance = abs(float(payload.get("tone", 0.0)))
    res = _assemble(payload, rng, importance, "clipping")
    if res is None:
        return None
    return res


def compose_news(fact: Dict[str, Any], tone: float, pub_name: str, week: int,
                 rng: random.Random, templates: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    payload = dict(fact or {})
    payload["tone"] = tone
    payload["publication"] = pub_name
    payload["week"] = week
    importance = abs(float(tone))
    res = _assemble(payload, rng, importance, "news")
    if res is None:
        return None
    return res["headline"], (res["lead"] + " " + res["body"]).strip()


def compose_consequences(script: Dict[str, Any], rng: random.Random,
                         templates: Dict[str, Any]) -> str:
    lex = _lexicons()
    reactors = script.get("reactors") or []
    secondary = script.get("secondary") or []
    parts: List[str] = []
    rp = _reactor_phrase(lex, [str(x) for x in reactors])
    if rp:
        parts.append(rp)
    for sec in secondary:
        parts.append(str(sec))
    if not parts:
        cons = _opt_list(lex, K_CONSEQUENCES)
        if cons:
            parts.append(str(rng.choice(cons)))
    return " ".join(parts)


def decorative_opener(rng: random.Random, decorative: Dict[str, Any]) -> str:
    openers = (decorative or {}).get("openers", []) or []
    return str(rng.choice(openers)) if openers else ""