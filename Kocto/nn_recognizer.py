from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from models import DataError, GameData, GameState

# ================= имена полей JSON (контракт схемы, НЕ контент) =================
K_RECOGNIZER = "recognizer"
K_FEATURE_WEIGHTS = "feature_weights"
K_INTENT_PRIORS = "intent_priors"
K_THRESHOLDS = "thresholds"
K_TH_HIGH = "high"
K_TH_MID = "mid"
K_TH_LOW = "low"
K_AMBIGUITY_GAP = "ambiguity_gap"
K_TEMPERATURE = "temperature"
K_CONTEXT_BONUS = "context_bonus"
K_LAW_FEATURES = "law_features"

K_INTENTS = "intents"
K_INTENT_ID = "intent_id"
K_VERBS = "verbs"
K_ENTITIES = "entities_allowed"
K_MODALITY_DEF = "modality_default"
K_ACTION_MAP = "action_mapping"
K_LEVEL_SCOPE = "level_scope"

K_DICT_VERBS = "verbs"
K_DICT_GROUPS = "groups"
K_DICT_ISSUES = "issues"
K_DICT_NPCS = "npcs"
K_DICT_RIVALS = "rivals"
K_DICT_PARTIES = "parties"
K_DICT_PUBS = "publications"
K_DICT_MODALITY = "modality"
K_DICT_NEGATION = "negation"
K_DICT_STOP = "stopwords"
K_DICT_TIME = "time_markers"
K_DICT_LEGAL = "legal_predicates"
K_DICT_ENFORCEMENT = "enforcement_markers"
K_DICT_BUDGET = "budget_markers"

K_PREDICATE = "predicate"
K_OBJECTS = "objects"
K_ENFORCEMENT = "enforcement"
K_BUDGET = "budget"
K_RAW = "raw"

# ================= имена признаков движка (контракт схемы, НЕ контент) =================
# Recognizer извлекает фиксированный набор непрерывных признаков; feature_weights
# обязан покрывать ВСЕ эти имена (значения-веса — из JSON). Отсутствие имени = ошибка конфигурации.
RECOGNIZER_FEATURES: Tuple[str, ...] = (
    "verb_score",
    "entity_score",
    "modality_match",
    "context_match",
    "negation_flag",
    "length_norm",
    "specificity",
    "typo_score",
    "level_weight",
)

LAW_FEATURES: Tuple[str, ...] = (
    "predicate_match",
    "object_count",
    "enforcement_present",
    "budget_present",
    "length_norm",
    "keyword_density",
)

ENTITY_SLOTS: Tuple[str, ...] = ("rival", "group", "party", "publication", "npc", "issue")


# ================= доступность модуля =================
def available() -> bool:
    """Модуль на месте = доступен. Полнота весов проверяется в recognize/type_law
    (единый источник правды о признаках — здесь, не в models.load_data)."""
    return True


# ================= валидатор секции recognizer (R2: адресная ошибка) =================
def _rec_section(data: GameData) -> Dict[str, Any]:
    nn = getattr(data, "nn", None) or {}
    weights = nn.get("weights") or {}
    if not isinstance(weights, dict) or K_RECOGNIZER not in weights:
        raise DataError("nn/weights.json: отсутствует секция 'recognizer' при включённом enabled_recognizer. "
                        "Вшитых дефолтов нет — добавь секцию в JSON.")
    rec = weights[K_RECOGNIZER]
    if not isinstance(rec, dict):
        raise DataError("nn/weights.json.recognizer: ожидался объект JSON.")
    for key in (K_FEATURE_WEIGHTS, K_INTENT_PRIORS, K_THRESHOLDS, K_LAW_FEATURES):
        if key not in rec:
            raise DataError("nn/weights.json.recognizer: отсутствует обязательная секция '" + str(key) + "'.")
    fw = rec[K_FEATURE_WEIGHTS]
    if not isinstance(fw, dict):
        raise DataError("nn/weights.json.recognizer.feature_weights: ожидался объект (имя признака -> вес).")
    missing_fw = [name for name in RECOGNIZER_FEATURES if name not in fw]
    if missing_fw:
        raise DataError("nn/weights.json.recognizer.feature_weights: нет весов для признаков: "
                        + ", ".join(missing_fw) + ". Все имена из RECOGNIZER_FEATURES обязаны быть заданы.")
    lf = rec[K_LAW_FEATURES]
    if not isinstance(lf, dict):
        raise DataError("nn/weights.json.recognizer.law_features: ожидался объект (имя признака -> вес).")
    missing_lf = [name for name in LAW_FEATURES if name not in lf]
    if missing_lf:
        raise DataError("nn/weights.json.recognizer.law_features: нет весов для признаков: "
                        + ", ".join(missing_lf) + ".")
    th = rec[K_THRESHOLDS]
    if not isinstance(th, dict):
        raise DataError("nn/weights.json.recognizer.thresholds: ожидался объект.")
    for tkey in (K_TH_HIGH, K_TH_MID, K_TH_LOW, K_AMBIGUITY_GAP):
        if tkey not in th:
            raise DataError("nn/weights.json.recognizer.thresholds: отсутствует ключ '" + str(tkey) + "'.")
    for nkey in (K_TEMPERATURE, K_CONTEXT_BONUS):
        if nkey not in rec:
            raise DataError("nn/weights.json.recognizer: отсутствует обязательный числовой ключ '" + str(nkey) + "'.")
    if not isinstance(rec[K_INTENT_PRIORS], dict):
        raise DataError("nn/weights.json.recognizer.intent_priors: ожидался объект (intent_id -> prior).")
    return rec


# ================= нормализация / токенизация (читает dictionaries.json, не вшивает) =================
def _known_words(dicts: Dict[str, Any]) -> set:
    words: set = set()
    for bucket in (dicts.get(K_DICT_VERBS, {}) or {}).values():
        if isinstance(bucket, list):
            words.update(str(w).lower() for w in bucket)
    for cat in (K_DICT_GROUPS, K_DICT_ISSUES, K_DICT_NPCS, K_DICT_RIVALS, K_DICT_PARTIES, K_DICT_PUBS):
        for aliases in (dicts.get(cat, {}) or {}).values():
            if isinstance(aliases, list):
                words.update(str(a).lower() for a in aliases)
            elif isinstance(aliases, str):
                words.add(aliases.lower())
    for cat in (K_DICT_MODALITY, K_DICT_NEGATION, K_DICT_TIME, K_DICT_STOP, K_DICT_LEGAL,
                K_DICT_ENFORCEMENT, K_DICT_BUDGET):
        val = dicts.get(cat)
        if isinstance(val, list):
            words.update(str(x).lower() for x in val)
        elif isinstance(val, dict):
            for sub in val.values():
                if isinstance(sub, list):
                    words.update(str(x).lower() for x in sub)
                elif isinstance(sub, str):
                    words.add(sub.lower())
    return words


def _tokens(text: str, dicts: Dict[str, Any]) -> List[str]:
    stops = set(str(s).lower() for s in (dicts.get(K_DICT_STOP, []) or []))
    raw = []
    buf = []
    for ch in (text or "").lower():
        if ch.isalnum() or ch in "_-":
            buf.append(ch)
        else:
            if buf:
                raw.append("".join(buf))
                buf = []
    if buf:
        raw.append("".join(buf))
    return [t for t in raw if t and t not in stops]


# ================= извлечение непрерывных признаков =================
def _verb_score(intent_verbs: List[str], toks: List[str]) -> float:
    if not intent_verbs or not toks:
        return 0.0
    token_set = set(toks)
    hit = sum(1 for v in intent_verbs if str(v).lower() in token_set)
    return hit / float(len(intent_verbs))


def _slot_aliases(dicts: Dict[str, Any], cat: str) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for sid, aliases in (dicts.get(cat, {}) or {}).items():
        if isinstance(aliases, list):
            out[str(sid)] = [str(a).lower() for a in aliases]
        elif isinstance(aliases, str):
            out[str(sid)] = [aliases.lower()]
    return out


def _entity_score(toks: List[str], dicts: Dict[str, Any], allowed: set) -> Tuple[float, str, str]:
    """Возвращает (скор 0..1, kind, id) по первому совпадению в приоритетном порядке слотов."""
    if not toks:
        return 0.0, "", ""
    token_set = set(toks)
    cat_map = {
        "rival": K_DICT_RIVALS, "group": K_DICT_GROUPS, "party": K_DICT_PARTIES,
        "publication": K_DICT_PUBS, "npc": K_DICT_NPCS, "issue": K_DICT_ISSUES,
    }
    for kind in ENTITY_SLOTS:
        if kind not in allowed:
            continue
        cat = cat_map.get(kind)
        if not cat:
            continue
        for sid, aliases in _slot_aliases(dicts, cat).items():
            if any(a in token_set for a in aliases):
                return 1.0, kind, sid
    return 0.0, "", ""


def _modality_flags(toks: List[str], dicts: Dict[str, Any]) -> Dict[str, bool]:
    flags = {"secret": False, "public": False, "urgent": False, "anonymous": False}
    token_set = set(toks)
    for key, aliases in (dicts.get(K_DICT_MODALITY, {}) or {}).items():
        al = aliases if isinstance(aliases, list) else [aliases]
        if any(str(a).lower() in token_set for a in al):
            flags[str(key)] = True
    return flags


def _negation_flag(toks: List[str], dicts: Dict[str, Any]) -> float:
    token_set = set(toks)
    joined = " ".join(toks)
    for a in (dicts.get(K_DICT_NEGATION, []) or []):
        aa = str(a).lower()
        if aa in token_set or aa in joined:
            return 1.0
    return 0.0


def _specificity(toks: List[str]) -> float:
    if not toks:
        return 0.0
    return len(set(toks)) / float(len(toks))


def _typo_score(toks: List[str], known: set) -> float:
    if not toks:
        return 0.0
    unknown = sum(1 for t in toks if t not in known)
    return unknown / float(len(toks))


def _level_weight(intent: Dict[str, Any], level: str) -> float:
    scope = intent.get(K_LEVEL_SCOPE, {}) or {}
    if not isinstance(scope, dict):
        return 1.0
    val = scope.get(level, 1.0)
    try:
        return float(val)
    except (TypeError, ValueError):
        return 1.0


def _extract_features(text: str, state: GameState, data: GameData) -> Dict[str, Any]:
    dicts = getattr(data, "dictionaries", None) or {}
    intents_doc = getattr(data, "intents", None) or {}
    intent_list = [it for it in (intents_doc.get(K_INTENTS, []) or []) if isinstance(it, dict)]
    level = getattr(state, "active_level", "city") or "city"
    toks = _tokens(text, dicts)
    known = _known_words(dicts)
    modality = _modality_flags(toks, dicts)
    neg = _negation_flag(toks, dicts)
    spec = _specificity(toks)
    typo = _typo_score(toks, known)
    length = float(len(toks))
    last_intent = str((getattr(state, "parser_context", {}) or {}).get("last_intent", ""))

    per_intent: Dict[str, Dict[str, float]] = {}
    targets: Dict[str, Tuple[str, str]] = {}
    for it in intent_list:
        iid = str(it.get(K_INTENT_ID, ""))
        if not iid:
            continue
        verbs = [str(v).lower() for v in (it.get(K_VERBS, []) or [])]
        allowed = set(str(x) for x in (it.get(K_ENTITIES, []) or []))
        vs = _verb_score(verbs, toks)
        es, kind, sid = _entity_score(toks, dicts, allowed)
        mod_def = str(it.get(K_MODALITY_DEF, "public")).lower()
        mm = 1.0 if (mod_def == "secret" and modality.get("secret")) or \
                    (mod_def == "public" and modality.get("public")) else 0.0
        cm = 1.0 if iid == last_intent else 0.0
        lw = _level_weight(it, level)
        per_intent[iid] = {
            "verb_score": vs, "entity_score": es, "modality_match": mm,
            "context_match": cm, "negation_flag": neg, "length_norm": length,
            "specificity": spec, "typo_score": typo, "level_weight": lw,
        }
        if sid:
            targets[iid] = (kind, sid)
    return {"per_intent": per_intent, "targets": targets, "toks": toks}


# ================= скоринг + softmax =================
def _softmax(scores: Dict[str, float], temperature: float) -> Dict[str, float]:
    if not scores:
        return {}
    t = float(temperature)
    if t <= 0.0:
        raise DataError("nn/weights.json.recognizer.temperature: должно быть > 0 (получено " + str(t) + ").")
    items = list(scores.items())
    mx = max(v for _, v in items)
    exps = {k: pow(2.718281828459045, (v - mx) / t) for k, v in items}
    total = sum(exps.values())
    if total <= 0.0:
        n = float(len(items))
        return {k: 1.0 / n for k, _ in items}
    return {k: exps[k] / total for k in exps}


def _raw_score(feat: Dict[str, float], fw: Dict[str, Any], prior: float,
               context_bonus: float) -> float:
    s = 0.0
    for name in RECOGNIZER_FEATURES:
        w = float(fw.get(name, 0.0))
        s += w * float(feat.get(name, 0.0))
    s += float(prior)
    s += float(context_bonus) * float(feat.get("context_match", 0.0))
    return s


# ================= маппинг intent -> action_id =================
def _map_action(intent: Dict[str, Any], kind: str) -> str:
    amap = intent.get(K_ACTION_MAP, "")
    if isinstance(amap, str):
        return amap
    if isinstance(amap, dict):
        return str(amap.get(kind, amap.get("default", "")))
    return ""


def _intent_doc(data: GameData) -> Dict[str, Dict[str, Any]]:
    intents_doc = getattr(data, "intents", None) or {}
    out: Dict[str, Dict[str, Any]] = {}
    for it in (intents_doc.get(K_INTENTS, []) or []):
        if isinstance(it, dict):
            iid = str(it.get(K_INTENT_ID, ""))
            if iid:
                out[iid] = it
    return out


# ================= главный вход распознавания =================
def recognize(text: str, state: GameState, data: GameData) -> Optional[Dict[str, Any]]:
    rec = _rec_section(data)
    fw = rec[K_FEATURE_WEIGHTS]
    priors = rec[K_INTENT_PRIORS]
    th = rec[K_THRESHOLDS]
    high = float(th[K_TH_HIGH])
    mid = float(th[K_TH_MID])
    low = float(th[K_TH_LOW])
    gap = float(th[K_AMBIGUITY_GAP])
    temp = float(rec[K_TEMPERATURE])
    cb = float(rec[K_CONTEXT_BONUS])

    feats = _extract_features(text, state, data)
    per_intent = feats["per_intent"]
    targets = feats["targets"]
    if not per_intent:
        return None

    raw_scores: Dict[str, float] = {}
    for iid, feat in per_intent.items():
        prior = float(priors.get(iid, 0.0))
        raw_scores[iid] = _raw_score(feat, fw, prior, cb)

    probs = _softmax(raw_scores, temp)
    ordered = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)
    best_iid, best_p = ordered[0]
    second_p = ordered[1][1] if len(ordered) > 1 else 0.0

    if best_p < low:
        return None

    ambiguous = (len(ordered) > 1) and ((best_p - second_p) < gap) and (best_p < high)

    intent = _intent_doc(data).get(best_iid, {})
    kind, sid = targets.get(best_iid, ("", ""))
    action_id = _map_action(intent, kind) or best_iid
    needs_body = (best_iid == "law_custom")
    delayed = False  # модальность времени решает парсер; recognizer не дублирует очередь

    explain = {
        "features": per_intent.get(best_iid, {}),
        "scores": {k: round(v, 4) for k, v in raw_scores.items()},
        "probs": {k: round(v, 4) for k, v in probs.items()},
        "thresholds": {"high": high, "mid": mid, "low": low, "ambiguity_gap": gap},
    }
    return {
        "id": action_id, "target": sid, "intent": best_iid,
        "confidence": round(best_p, 4), "delayed": delayed, "needs_body": needs_body,
        "ambiguous": bool(ambiguous), "explain": explain,
    }


# ================= типизация свободного закона (Q-D) =================
def _law_predicate_score(toks: List[str], dicts: Dict[str, Any]) -> Tuple[str, float]:
    legal = dicts.get(K_DICT_LEGAL, []) or []
    if not legal:
        laws = getattr(dicts, "laws", None)  # не ожидается; fallback ниже через data
        legal = []
    token_set = set(toks)
    best = ""
    best_hit = 0.0
    for p in legal:
        pp = str(p).lower()
        if pp in token_set:
            return pp, 1.0
        # частичное вхождение как слабый сигнал
        if pp and any(pp in t or t in pp for t in token_set):
            best = best or pp
            best_hit = max(best_hit, 0.5)
    return best, best_hit


def type_law(text: str, state: GameState, data: GameData) -> Optional[Dict[str, Any]]:
    rec = _rec_section(data)
    lf = rec[K_LAW_FEATURES]
    th = rec[K_THRESHOLDS]
    low = float(th[K_TH_LOW])
    temp = float(rec[K_TEMPERATURE])

    dicts = getattr(data, "dictionaries", None) or {}
    legal = dicts.get(K_DICT_LEGAL, []) or []
    if not legal:
        laws_cfg = getattr(data, "laws", None) or {}
        legal = laws_cfg.get("legal_predicates", []) or []
    if not legal:
        raise DataError("nn_recognizer.type_law: нет legal_predicates ни в dictionaries.json, ни в laws.json. "
                        "Свободные законы не типизируются.")

    toks = _tokens(text, dicts)
    token_set = set(toks)
    predicate, pred_hit = _law_predicate_score(toks, dicts)

    objects: List[str] = []
    for sid, aliases in _slot_aliases(dicts, K_DICT_GROUPS).items():
        if any(a in token_set for a in aliases):
            objects.append(sid)

    enforcement = ""
    for e in (dicts.get(K_DICT_ENFORCEMENT, {}) or {}):
        if str(e).lower() in token_set:
            enforcement = str(e).lower()
            break
    budget = ""
    for b in (dicts.get(K_DICT_BUDGET, {}) or {}):
        if str(b).lower() in token_set:
            budget = str(b).lower()
            break

    length = float(len(toks))
    known = _known_words(dicts)
    legal_set = set(str(p).lower() for p in legal)
    keyword_hits = sum(1 for t in toks if t in legal_set)
    keyword_density = (keyword_hits / length) if length > 0.0 else 0.0

    feat = {
        "predicate_match": float(pred_hit),
        "object_count": float(len(objects)),
        "enforcement_present": 1.0 if enforcement else 0.0,
        "budget_present": 1.0 if budget else 0.0,
        "length_norm": length,
        "keyword_density": float(keyword_density),
    }
    raw = 0.0
    for name in LAW_FEATURES:
        raw += float(lf.get(name, 0.0)) * float(feat.get(name, 0.0))
    probs = _softmax({"law": raw}, temp)
    conf = float(probs.get("law", 0.0))

    skeleton = {
        K_PREDICATE: predicate or "символический",
        K_OBJECTS: objects,
        K_ENFORCEMENT: enforcement or "нет",
        K_BUDGET: budget or "нет",
        K_RAW: text,
        "confidence": round(conf, 4),
        "explain": {"features": {k: round(float(v), 4) for k, v in feat.items()},
                    "raw_score": round(raw, 4)},
    }
    if conf < low and not predicate:
        return None
    return skeleton