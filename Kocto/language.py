from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from models import (DataError, GameState, ParseStatus, load_json, save_json,
                    user_data_path, NN_MEMORY_CONSTRUCTIONS)

# ---- имена полей JSON (контракт схемы, НЕ контент) ----
K_SCHEMA = "schema_version"
K_INTENTS = "intents"
K_THRESHOLDS = "thresholds"
K_TH_HIGH = "high"
K_TH_MID = "mid"
K_INTENT_ID = "intent_id"
K_LABEL = "label"
K_VERBS = "verbs"
K_ENTITIES = "entities_allowed"
K_MODALITY_DEF = "modality_default"
K_NEGATION = "negation_behavior"
K_AGGRESSIVE = "aggressive"
K_ACTION_MAP = "action_mapping"
K_EFFECT_REF = "effect_template_ref"
K_LEVEL_SCOPE = "level_scope"
K_CONF_FLOOR = "confidence_floor"

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
K_DICT_SEPARATORS = "separators"
K_DICT_SYNONYMS = "synonyms"
K_DICT_TYPOS = "typos"
K_DICT_TYPO_CUTOFF = "typo_cutoff"
K_DICT_STEMS = "stem_map"
K_DICT_CONTEXT = "context_shortcuts"
K_DICT_LEGAL = "legal_predicates"
K_DICT_ENFORCEMENT = "enforcement_markers"
K_DICT_BUDGET = "budget_markers"

# ---- кэш загруженных конструкций (рантайм-файл в USER-папке) ----
_CONSTRUCTIONS: Dict[str, Any] = {"constructions": []}
_CONSTRUCTIONS_PATH: Optional[Path] = None


def _require_intents(data: Any) -> Dict[str, Any]:
    intents = getattr(data, "intents", None)
    if not isinstance(intents, dict):
        raise DataError("language: data.intents отсутствует (ожидался объект из intents/intents.json).")
    if K_THRESHOLDS not in intents:
        raise DataError("intents/intents.json: отсутствует обязательная секция 'thresholds' "
                        "(пороги уверенности high/mid). Вшитых дефолтов нет — добавь ключ в JSON.")
    th = intents[K_THRESHOLDS]
    if not isinstance(th, dict) or K_TH_HIGH not in th or K_TH_MID not in th:
        raise DataError("intents/intents.json.thresholds: нужны числовые ключи 'high' и 'mid'.")
    if K_INTENTS not in intents or not isinstance(intents[K_INTENTS], list) or not intents[K_INTENTS]:
        raise DataError("intents/intents.json: отсутствует или пуст массив 'intents'.")
    return intents


def _require_dicts(data: Any) -> Dict[str, Any]:
    dicts = getattr(data, "dictionaries", None)
    if not isinstance(dicts, dict):
        raise DataError("language: data.dictionaries отсутствует (ожидался объект из parser/dictionaries.json).")
    return dicts


def _intent_list(intents: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [it for it in intents[K_INTENTS] if isinstance(it, dict)]


def _all_verbs(intents: Dict[str, Any], dicts: Dict[str, Any]) -> List[str]:
    verbs: List[str] = []
    for it in _intent_list(intents):
        verbs.extend(str(v).lower() for v in it.get(K_VERBS, []))
    for bucket in dicts.get(K_DICT_VERBS, {}) or {}:
        vals = dicts[K_DICT_VERBS][bucket]
        if isinstance(vals, list):
            verbs.extend(str(v).lower() for v in vals)
    return verbs


# ================= нормализация =================
def normalize(text: str, dicts: Optional[Dict[str, Any]] = None) -> str:
    t = (text or "").lower().strip()
    t = re.sub(r"[^\w\s\-а-яёё]", " ", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t)
    if not dicts:
        return t
    stops = set(str(s).lower() for s in dicts.get(K_DICT_STOP, []) or [])
    stems = {str(k).lower(): str(v).lower() for k, v in (dicts.get(K_DICT_STEMS, {}) or {}).items()}
    syns = dicts.get(K_DICT_SYNONYMS, {}) or {}
    out_tokens: List[str] = []
    for tok in t.split():
        if tok in stops:
            continue
        tok = stems.get(tok, tok)
        # синонимы: map слово -> список/строка канонических форм
        canon = syns.get(tok)
        if isinstance(canon, str):
            tok = canon
        elif isinstance(canon, list) and canon:
            tok = str(canon[0]).lower()
        out_tokens.append(tok)
    return " ".join(out_tokens)


def _tokens(text: str, dicts: Optional[Dict[str, Any]] = None) -> List[str]:
    return normalize(text, dicts).split()


# ================= память конструкций (обучение формулировкам) =================
def init_constructions(user_dir: Optional[Path] = None) -> None:
    global _CONSTRUCTIONS, _CONSTRUCTIONS_PATH
    _CONSTRUCTIONS_PATH = user_data_path(NN_MEMORY_CONSTRUCTIONS) if user_dir is None \
        else Path(user_dir) / NN_MEMORY_CONSTRUCTIONS
    loaded = load_json(_CONSTRUCTIONS_PATH, {"constructions": []}) or {}
    if not isinstance(loaded, dict) or "constructions" not in loaded:
        loaded = {"constructions": []}
    _CONSTRUCTIONS = loaded


def _save_constructions() -> None:
    if _CONSTRUCTIONS_PATH is not None:
        save_json(_CONSTRUCTIONS_PATH, _CONSTRUCTIONS)


def remember_construction(features: Dict[str, Any], intent: str, action_id: str, raw: str) -> None:
    if not _CONSTRUCTIONS_PATH:
        init_constructions()
    key = _feature_key(features)
    items = _CONSTRUCTIONS.setdefault("constructions", [])
    for it in items:
        if it.get("key") == key:
            it["intent"] = intent
            it["action_id"] = action_id
            it["hits"] = int(it.get("hits", 1)) + 1
            it["last_raw"] = raw
            _save_constructions()
            return
    items.append({"key": key, "intent": intent, "action_id": action_id, "hits": 1, "last_raw": raw})
    # ограничение размера (движок, не баланс-контент): держим последние 200
    while len(items) > 200:
        items.pop(0)
    _save_constructions()


def match_construction(features: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    if not _CONSTRUCTIONS_PATH:
        init_constructions()
    key = _feature_key(features)
    for it in reversed(_CONSTRUCTIONS.get("constructions", [])):
        if it.get("key") == key:
            return str(it.get("intent", "")), str(it.get("action_id", ""))
    return None


def _feature_key(features: Dict[str, Any]) -> str:
    # детерминированный ключ по сортированным признакам (без вшитых слов)
    parts: List[str] = []
    for k in sorted(features.keys()):
        v = features[k]
        if isinstance(v, (list, tuple, set)):
            parts.append(f"{k}=" + ",".join(sorted(str(x) for x in v)))
        elif isinstance(v, dict):
            parts.append(f"{k}=" + ",".join(f"{kk}:{v[kk]}" for kk in sorted(v.keys())))
        else:
            parts.append(f"{k}={v}")
    return "|".join(parts)


# ================= извлечение признаков =================
def extract_features(text: str, state: GameState, data: Any) -> Dict[str, Any]:
    dicts = _require_dicts(data)
    intents = _require_intents(data)
    toks = _tokens(text, dicts)
    token_set = set(toks)

    verb_hits: Dict[str, int] = {}
    for it in _intent_list(intents):
        iid = str(it.get(K_INTENT_ID, ""))
        hits = 0
        for v in it.get(K_VERBS, []) or []:
            vv = str(v).lower()
            if vv in token_set:
                hits += 1
            elif _fuzzy_in(vv, toks, dicts):
                hits += 1
        if hits:
            verb_hits[iid] = hits

    entities = _detect_entities(toks, dicts, state)
    modality = _detect_modality(toks, dicts)
    negation = _detect_negation(toks, dicts)
    delayed = _detect_delay(toks, dicts)

    return {
        "tokens": toks,
        "verb_hits": verb_hits,
        "entities": entities,
        "modality": modality,
        "negation": negation,
        "delayed": delayed,
    }


def _fuzzy_in(needle: str, toks: List[str], dicts: Dict[str, Any]) -> bool:
    cutoff = float(dicts.get(K_DICT_TYPO_CUTOFF, 0.0) or 0.0)
    if cutoff <= 0.0:
        return False
    typos = dicts.get(K_DICT_TYPOS, {}) or {}
    if needle in typos and str(typos[needle]).lower() in toks:
        return True
    matches = difflib.get_close_matches(needle, toks, n=1, cutoff=cutoff)
    return bool(matches)


def _detect_entities(toks: List[str], dicts: Dict[str, Any], state: GameState) -> Dict[str, str]:
    ents: Dict[str, str] = {}
    token_set = set(toks)

    groups = dicts.get(K_DICT_GROUPS, {}) or {}
    for gid, aliases in groups.items():
        alias_list = aliases if isinstance(aliases, list) else [aliases]
        if any(str(a).lower() in token_set for a in alias_list):
            ents["group"] = str(gid)
            break

    issues = dicts.get(K_DICT_ISSUES, {}) or {}
    for iid, aliases in issues.items():
        alias_list = aliases if isinstance(aliases, list) else [aliases]
        if any(str(a).lower() in token_set for a in alias_list):
            ents["issue"] = str(iid)
            break

    npcs = dicts.get(K_DICT_NPCS, {}) or {}
    for nid, aliases in npcs.items():
        alias_list = aliases if isinstance(aliases, list) else [aliases]
        if any(str(a).lower() in token_set for a in alias_list):
            ents["npc"] = str(nid)
            break

    rivals = dicts.get(K_DICT_RIVALS, {}) or {}
    for rid, aliases in rivals.items():
        alias_list = aliases if isinstance(aliases, list) else [aliases]
        if any(str(a).lower() in token_set for a in alias_list):
            ents["rival"] = str(rid)
            break

    parties = dicts.get(K_DICT_PARTIES, {}) or {}
    for pid, aliases in parties.items():
        alias_list = aliases if isinstance(aliases, list) else [aliases]
        if any(str(a).lower() in token_set for a in alias_list):
            ents["party"] = str(pid)
            break

    pubs = dicts.get(K_DICT_PUBS, {}) or {}
    for pbid, aliases in pubs.items():
        alias_list = aliases if isinstance(aliases, list) else [aliases]
        if any(str(a).lower() in token_set for a in alias_list):
            ents["publication"] = str(pbid)
            break

    # контекстные сокращения (опционально): map "о дорогах" -> {group:..., issue:...}
    shortcuts = dicts.get(K_DICT_CONTEXT, {}) or {}
    for phrase, slotmap in shortcuts.items():
        if str(phrase).lower() in " ".join(toks) and isinstance(slotmap, dict):
            for k, v in slotmap.items():
                ents.setdefault(str(k), str(v))
    return ents


def _detect_modality(toks: List[str], dicts: Dict[str, Any]) -> Dict[str, bool]:
    mod = {"secret": False, "public": False, "urgent": False, "anonymous": False}
    bucket = dicts.get(K_DICT_MODALITY, {}) or {}
    token_set = set(toks)
    for key, aliases in bucket.items():
        alias_list = aliases if isinstance(aliases, list) else [aliases]
        if any(str(a).lower() in token_set for a in alias_list):
            mod[str(key)] = True
    return mod


def _detect_negation(toks: List[str], dicts: Dict[str, Any]) -> bool:
    bucket = dicts.get(K_DICT_NEGATION, []) or []
    alias_list = bucket if isinstance(bucket, list) else [bucket]
    token_set = set(toks)
    joined = " ".join(toks)
    for a in alias_list:
        aa = str(a).lower()
        if aa in token_set or aa in joined:
            return True
    return False


def _detect_delay(toks: List[str], dicts: Dict[str, Any]) -> bool:
    bucket = dicts.get(K_DICT_TIME, []) or []
    alias_list = bucket if isinstance(bucket, list) else [bucket]
    joined = " ".join(toks)
    for a in alias_list:
        if str(a).lower() in joined:
            return True
    return False


# ================= скоринг intent =================
def _level_weight(it: Dict[str, Any], level: str) -> float:
    scope = it.get(K_LEVEL_SCOPE, {}) or {}
    if not isinstance(scope, dict):
        return 1.0
    val = scope.get(level, 1.0)
    try:
        return float(val)
    except (TypeError, ValueError):
        return 1.0


def _score_intent(it: Dict[str, Any], features: Dict[str, Any], dicts: Dict[str, Any],
                  level: str) -> Tuple[float, str, str]:
    """Возвращает (уверенность, intent_id, action_id)."""
    iid = str(it.get(K_INTENT_ID, ""))
    verbs = it.get(K_VERBS, []) or []
    if not verbs:
        return 0.0, iid, ""
    verb_hit = 1 if features["verb_hits"].get(iid, 0) > 0 else 0
    ents = features["entities"]
    allowed = set(str(x) for x in (it.get(K_ENTITIES, []) or []))
    target_kind, target_id = _resolve_target(allowed, ents, it)
    target_present = 1 if target_id else 0
    issue_present = 1 if (ents.get("issue") and "issue" in allowed) else 0

    base = (verb_hit + target_present + 0.5 * issue_present) / 2.0
    modality = features["modality"]
    mod_def = str(it.get(K_MODALITY_DEF, "public")).lower()
    mod_weight = 1.0
    if mod_def == "secret" and modality.get("secret"):
        mod_weight = 1.2
    elif mod_def == "public" and modality.get("public"):
        mod_weight = 1.1
    elif mod_def == "secret" and not modality.get("secret"):
        mod_weight = 0.8

    conf = max(0.0, min(1.5, base * mod_weight))
    conf *= _level_weight(it, level)

    floor = float(it.get(K_CONF_FLOOR, 0.0) or 0.0)
    if conf < floor:
        conf = 0.0

    action_id = _map_action(it, target_kind, target_id)
    return conf, iid, action_id


def _resolve_target(allowed: set, ents: Dict[str, str], it: Dict[str, Any]) -> Tuple[str, str]:
    # приоритет слотов: rival > group > party > publication > npc > issue
    order = ["rival", "group", "party", "publication", "npc", "issue"]
    for kind in order:
        if kind in allowed and ents.get(kind):
            return kind, str(ents[kind])
    # если разрешён generic target, но конкретных нет — пустой
    return "", ""


def _map_action(it: Dict[str, Any], target_kind: str, target_id: str) -> str:
    amap = it.get(K_ACTION_MAP, "")
    if isinstance(amap, str):
        return amap
    if isinstance(amap, dict):
        # map по типу цели, иначе default
        return str(amap.get(target_kind, amap.get("default", "")))
    return ""


# ================= типизация свободного закона (Q-D) =================
def type_law_text(text: str, state: GameState, data: Any) -> Dict[str, Any]:
    dicts = _require_dicts(data)
    legal = dicts.get(K_DICT_LEGAL, []) or []
    if not legal:
        laws = getattr(data, "laws", {}) or {}
        legal = laws.get("legal_predicates", []) or []
    if not legal:
        raise DataError("language.type_law_text: нет legal_predicates ни в dictionaries.json, "
                        "ни в laws.json — свободные законы не типизируются.")
    toks = _tokens(text, dicts)
    token_set = set(toks)
    predicate = ""
    for p in legal:
        pp = str(p).lower()
        if pp in token_set or _fuzzy_in(pp, toks, dicts):
            predicate = pp
            break
    objects: List[str] = []
    groups = dicts.get(K_DICT_GROUPS, {}) or {}
    for gid, aliases in groups.items():
        alias_list = aliases if isinstance(aliases, list) else [aliases]
        if any(str(a).lower() in token_set for a in alias_list):
            objects.append(str(gid))
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
    return {"predicate": predicate or "символический", "objects": objects,
            "enforcement": enforcement or "нет", "budget": budget or "нет",
            "raw": text}


# ================= разбор одной фразы (правило+память+конструкция) =================
def _parse_one(text: str, state: GameState, memory: Dict[str, Any], data: Any) -> Dict[str, Any]:
    dicts = _require_dicts(data)
    intents = _require_intents(data)
    level = getattr(state, "active_level", "city") or "city"
    th = intents[K_THRESHOLDS]
    high = float(th[K_TH_HIGH])
    mid = float(th[K_TH_MID])

    norm = normalize(text, dicts)
    if not norm:
        return {"status": ParseStatus.UNKNOWN, "message": "Пустая фраза."}

    # 1) память фраз (LRU из main): готовый action_id
    mem = memory.get(norm) if isinstance(memory, dict) else None
    if isinstance(mem, dict) and mem.get("id"):
        return {"status": ParseStatus.PARSED, "source": "memory",
                "id": str(mem["id"]), "intent": str(mem.get("intent", "")),
                "target": "", "delayed": False, "confidence": 1.0, "needs_body": False,
                "message": "Распознано по памяти."}

    features = extract_features(text, state, data)

    # 2) память конструкций (обученные формулировки)
    mc = match_construction(features)
    if mc:
        intent_id, action_id = mc
        if action_id:
            return {"status": ParseStatus.PARSED, "source": "construction",
                    "id": action_id, "intent": intent_id, "target": "",
                    "delayed": bool(features["delayed"]), "confidence": 0.9, "needs_body": False,
                    "message": "Распознано по конструкции."}

    # 3) скоринг всех intent-типов
    scored: List[Tuple[float, str, str, Dict[str, Any]]] = []
    for it in _intent_list(intents):
        conf, iid, action_id = _score_intent(it, features, dicts, level)
        if conf > 0.0:
            scored.append((conf, iid, action_id, it))
    scored.sort(key=lambda x: x[0], reverse=True)

    if not scored:
        # контекстный вывод: есть группа/тема/НПС -> пробуем Публичные по контексту
        ctx = _contextual_fallback(features, intents, level)
        if ctx:
            return ctx
        return {"status": ParseStatus.NEEDS_REFORMULATION,
                "message": "Не понял. Переформулируй: глагол + цель (группа/соперник/партия/издание) + тема."}

    best_conf, best_iid, best_action, best_it = scored[0]

    # отрицание (из JSON: negation_behavior + aggressive)
    if features["negation"]:
        neg_behavior = str(best_it.get(K_NEGATION, "refuse")).lower()
        aggressive = bool(best_it.get(K_AGGRESSIVE, False))
        if neg_behavior == "cancel" or (aggressive and neg_behavior != "invert"):
            return {"status": ParseStatus.CANCELLED, "aggressive": True,
                    "message": f"Отмена: {best_it.get(K_LABEL, best_iid)}."}
        return {"status": ParseStatus.CANCELLED, "aggressive": False,
                "message": f"Действие-отказ вместо {best_it.get(K_LABEL, best_iid)}."}

    # пороги
    if best_conf >= high:
        target_kind, target_id = _resolve_target(set(str(x) for x in (best_it.get(K_ENTITIES, []) or [])),
                                                 features["entities"], best_it)
        needs_body = (best_iid == "law_custom")
        return {"status": ParseStatus.PARSED, "source": "parser",
                "id": best_action or best_iid, "intent": best_iid,
                "target": target_id, "delayed": bool(features["delayed"]),
                "confidence": round(best_conf, 3), "needs_body": needs_body,
                "message": ""}

    if best_conf >= mid:
        # NeedsChoice: 2-3 трактовки
        options = []
        seen = set()
        for conf, iid, action_id, it in scored[:3]:
            if iid in seen:
                continue
            seen.add(iid)
            options.append({"intent": iid, "action_id": action_id or iid,
                            "label": str(it.get(K_LABEL, iid)), "confidence": round(conf, 3)})
        return {"status": ParseStatus.NEEDS_CHOICE, "source": "parser",
                "options": options, "delayed": bool(features["delayed"]),
                "message": "Несколько трактовок — выбери номер."}

    # ниже mid: контекстный вывод или переформулировка
    ctx = _contextual_fallback(features, intents, level)
    if ctx:
        return ctx
    return {"status": ParseStatus.NEEDS_REFORMULATION,
            "message": "Слишком неуверенно. Добавь глагол и цель."}


def _contextual_fallback(features: Dict[str, Any], intents: Dict[str, Any], level: str) -> Optional[Dict[str, Any]]:
    ents = features["entities"]
    if not (ents.get("group") or ents.get("issue") or ents.get("npc") or ents.get("rival")):
        return None
    # ищем тип, который принимает хотя бы один из присутствующих слотов и имеет глагол-контекст по умолчанию
    for it in _intent_list(intents):
        allowed = set(str(x) for x in (it.get(K_ENTITIES, []) or []))
        if not allowed:
            continue
        present = [k for k in ("rival", "group", "party", "publication", "npc", "issue") if k in allowed and ents.get(k)]
        if not present:
            continue
        conf, iid, action_id = _score_intent(it, features, {}, level)
        # контекстный бонус: presence слота без прямого глагола -> 0.55 (движок понимания, не баланс-контент)
        conf = max(conf, 0.55) * _level_weight(it, level)
        if conf >= 0.5:
            kind = present[0]
            return {"status": ParseStatus.PARSED, "source": "context",
                    "id": action_id or iid, "intent": iid, "target": str(ents[kind]),
                    "delayed": bool(features["delayed"]), "confidence": round(conf, 3),
                    "needs_body": (iid == "law_custom"), "message": "Выведено по контексту."}
    return None


# ================= разбиение на части (>3 действий -> отказ) =================
def _split_parts(text: str, dicts: Dict[str, Any]) -> List[str]:
    seps = dicts.get(K_DICT_SEPARATORS, []) or []
    pattern = "|".join(re.escape(str(s)) for s in seps) if seps else r"[;,]"
    parts = [p.strip() for p in re.split(pattern, text) if p.strip()]
    return parts


# ================= A/B канал (парсер vs НС-recognizer) =================
def _nn_available(data: Any) -> bool:
    nn = getattr(data, "nn", {}) or {}
    if not bool(nn.get("enabled_recognizer", False)):
        return False
    try:
        import nn_recognizer  # noqa: F401
        return nn_recognizer.available()
    except Exception:
        return False


def _nn_proposal(text: str, state: GameState, data: Any) -> Optional[Dict[str, Any]]:
    try:
        import nn_recognizer
        return nn_recognizer.recognize(text, state, data)
    except Exception:
        return None


# ================= главный вход =================
def parse_text(text: str, state: GameState, memory: Dict[str, Any], data: Any) -> Dict[str, Any]:
    dicts = _require_dicts(data)
    parts = _split_parts(text, dicts)
    if len(parts) > 3:
        return {"status": ParseStatus.TOO_MANY_ACTIONS, "actions": [], "ab_proposals": [],
                "message": "Больше трёх действий в одной фразе — разбей на отдельные команды."}

    actions: List[Dict[str, Any]] = []
    ab_proposals: List[Dict[str, Any]] = []
    use_ab = bool(getattr(state, "ab_mode", False)) and _nn_available(data)

    for part in parts:
        parsed = _parse_one(part, state, memory, data)
        status = parsed.get("status")

        if status in (ParseStatus.NEEDS_CHOICE, ParseStatus.NEEDS_REFORMULATION,
                      ParseStatus.TOO_MANY_ACTIONS, ParseStatus.CANCELLED, ParseStatus.UNKNOWN):
            # непройденная часть — возвращаем как есть (main обработает выбор/отказ)
            return {"status": status, "actions": actions, "ab_proposals": ab_proposals,
                    "message": parsed.get("message", ""), "aggressive": parsed.get("aggressive", False),
                    "options": parsed.get("options", [])}

        # PARSED
        if use_ab:
            nn_prop = _nn_proposal(part, state, data)
            parser_prop = {"id": parsed.get("id", ""), "target": parsed.get("target", ""),
                           "intent": parsed.get("intent", ""), "confidence": parsed.get("confidence", 0.0),
                           "delayed": parsed.get("delayed", False), "needs_body": parsed.get("needs_body", False)}
            ab_proposals.append({"parser": parser_prop, "nn": nn_prop})
            # в A/B не фиксируем действие сразу — main покажет выбор
            continue

        actions.append({k: parsed.get(k) for k in
                        ("id", "intent", "target", "delayed", "confidence", "source", "needs_body")})

    if use_ab and ab_proposals and not actions:
        return {"status": ParseStatus.PARSED, "actions": [], "ab_proposals": ab_proposals,
                "message": "Выбери источник распознавания (парсер/нейросеть)."}

    if not actions and not ab_proposals:
        return {"status": ParseStatus.UNKNOWN, "actions": [], "ab_proposals": [],
                "message": "Не распознано."}

    return {"status": ParseStatus.PARSED, "actions": actions, "ab_proposals": ab_proposals,
            "message": ""}


# ================= контекст для следующих фраз =================
def update_context(state: GameState, text: str, parse_result: Dict[str, Any]) -> None:
    ctx = getattr(state, "parser_context", None)
    if ctx is None:
        state.parser_context = {}
        ctx = state.parser_context
    actions = parse_result.get("actions") or []
    if actions:
        a = actions[0]
        ctx["last_intent"] = a.get("intent", "")
        ctx["last_target"] = a.get("target", "")
        ctx["last_issue"] = ""
    opts = parse_result.get("options") or []
    if opts:
        ctx["pending_options"] = opts
    ab = parse_result.get("ab_proposals") or []
    if ab:
        ctx["pending_ab"] = ab