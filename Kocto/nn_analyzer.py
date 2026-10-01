from __future__ import annotations

import copy
import json
import math
import random
from typing import Any, Dict, List, Optional, Tuple

from models import (ActionData, DataError, ElectoralSystem, GameData, GameState,
                    PrisonStatus, Role)

# ================= имена полей JSON (контракт схемы, НЕ контент) =================
K_ANALYZER = "analyzer"
K_FEATURE_WEIGHTS = "feature_weights"
K_TIER_PRIORS = "tier_priors"
K_EFFECT_SCALES = "effect_scales"
K_CASCADE = "cascade"
K_NETWORK_LINKS = "network_links"
K_MAX_DEPTH = "max_depth"
K_DECAY = "decay"
K_PLAUS_MODEL = "plausibility_model"
K_PM_BASE = "base"
K_PM_TOP = "top_prob_weight"
K_PM_JITTER = "jitter"
K_PM_DRIFT = "drift_penalty"
K_PM_OVERRIDE = "override_bonus"
K_PM_COMPLETENESS = "completeness_weight"
K_MAG_MODEL = "magnitude_model"
K_MM_BASE = "base"
K_MM_TOP = "top_prob_weight"
K_MM_JITTER = "jitter"
K_DRIFT = "drift"
K_D_BOUND = "bound"
K_D_PENALTY = "plaus_penalty"
K_PATCH_RULES = "patch_rules"
K_KEYWORD_MAP = "keyword_map"
K_DEFAULT_OPS = "default_ops"
K_THRESHOLDS = "thresholds"
K_TH_MIN_PLAUS = "min_plausibility"
K_TH_AMBIGUITY = "ambiguity_gap"
K_TEMPERATURE = "temperature"
K_REASON_FEATURES = "reason_features"
K_ROLE_MAP = "role_map"
K_PRISON_MAP = "prison_severity_map"
K_LAW_MODEL = "law_model"
K_PRED_POLARITY = "predicate_polarity"
K_PRED_BUDGET = "predicate_budget"
K_ENF_BUDGET = "enforcement_budget"
K_COMPLETENESS_SLOTS = "completeness_slots"

K_PRIMARY = "primary"
K_SECONDARY = "secondary"
K_REACTORS = "reactors"
K_TONE = "tone"
K_TONE_VECTOR = "tone_vector"
K_POLARITY = "polarity"
K_INTENSITY = "intensity"
K_TIER_DISTRIBUTION = "tier_distribution"
K_REASON_KEY = "reason_key"
K_EFFECTS = "effects"
K_PLAUSIBILITY = "plausibility"
K_DELAYED = "delayed"
K_PLAYER_OVERRIDE = "player_override"
K_PLAYER_CORRECTION = "player_correction"
K_IS_ACTUAL = "is_actual"

K_EFF_TYPE = "type"
K_EFF_GROUP = "group"
K_EFF_STAT = "stat"
K_EFF_DELTA = "delta"
K_EFF_SUBJECT = "subject"
K_EFF_KIND = "kind"

K_SKELETON = "typed_skeleton"
K_PREDICATE = "predicate"
K_OBJECTS = "objects"
K_ENFORCEMENT = "enforcement"
K_BUDGET = "budget"
K_TITLE = "title"

# ================= enum-контракты (структура, НЕ контент) =================
TIERS: Tuple[str, ...] = ("great", "solid", "complication", "minor", "major", "catastrophe")
TIER_SIGN: Dict[str, int] = {"great": 1, "solid": 1, "complication": 0,
                             "minor": -1, "major": -1, "catastrophe": -1}
TIER_MIRROR: Dict[str, str] = {"great": "catastrophe", "solid": "major", "complication": "minor",
                               "minor": "complication", "major": "solid", "catastrophe": "great"}
ROLE_VALUES: Tuple[str, ...] = tuple(r.value for r in Role)
PRISON_VALUES: Tuple[str, ...] = tuple(p.value for p in PrisonStatus)
EFFECT_TYPES: Tuple[str, ...] = ("group_mood", "group_loyalty", "player_stat",
                                 "treasury", "player_money", "support")

# Шкала индексов 0..100 — инвариант схемы данных models (mood/loyalty/awareness/... Clamp 0..100),
# тот же класс, что clamp(...,0,100) в systems; не тюнинг-баланс, нормализатор шкалы.
SCALE = 100.0

# ================= имена признаков контекста (контракт схемы, НЕ контент) =================
# feature_weights обязан покрывать ВСЕ эти имена (значения-веса — из JSON).
ANALYZER_FEATURES: Tuple[str, ...] = (
    "role_weight",
    "prison_weight",
    "salience",
    "relationship",
    "fatigue",
    "history_repeat",
    "aggression",
    "secrecy",
    "risk_norm",
    "target_size_norm",
    "mood_baseline",
    "loyalty_baseline",
    "trust_norm",
    "anti_norm",
    "scandal_norm",
    "seats_norm",
    "promise_pressure",
    "institutional",
    "fresh_fact",
)

# ================= доступность =================
def available() -> bool:
    return True


# ================= валидатор секции analyzer (R2: адресная ошибка) =================
def _weights_analyzer(data: GameData) -> Dict[str, Any]:
    nn = getattr(data, "nn", None) or {}
    weights = nn.get("weights") or {}
    if not isinstance(weights, dict) or K_ANALYZER not in weights:
        raise DataError("nn/weights.json: отсутствует секция 'analyzer' при включённом enabled_analyzer. "
                        "Вшитых дефолтов нет — добавь секцию в JSON.")
    an = weights[K_ANALYZER]
    if not isinstance(an, dict):
        raise DataError("nn/weights.json.analyzer: ожидался объект JSON.")
    for key in (K_FEATURE_WEIGHTS, K_TIER_PRIORS, K_EFFECT_SCALES, K_CASCADE, K_PLAUS_MODEL,
                K_MAG_MODEL, K_DRIFT, K_PATCH_RULES, K_THRESHOLDS, K_TEMPERATURE,
                K_REASON_FEATURES, K_ROLE_MAP, K_PRISON_MAP, K_LAW_MODEL):
        if key not in an:
            raise DataError("nn/weights.json.analyzer: отсутствует обязательная секция '" + str(key) + "'.")
    fw = an[K_FEATURE_WEIGHTS]
    if not isinstance(fw, dict):
        raise DataError("nn/weights.json.analyzer.feature_weights: ожидался объект (имя признака -> вес).")
    miss_fw = [n for n in ANALYZER_FEATURES if n not in fw]
    if miss_fw:
        raise DataError("nn/weights.json.analyzer.feature_weights: нет весов для признаков: "
                        + ", ".join(miss_fw) + ".")
    tp = an[K_TIER_PRIORS]
    if not isinstance(tp, dict):
        raise DataError("nn/weights.json.analyzer.tier_priors: ожидался объект.")
    miss_tp = [t for t in TIERS if t not in tp]
    if miss_tp:
        raise DataError("nn/weights.json.analyzer.tier_priors: нет априора для тиров: " + ", ".join(miss_tp) + ".")
    es = an[K_EFFECT_SCALES]
    if not isinstance(es, dict):
        raise DataError("nn/weights.json.analyzer.effect_scales: ожидался объект.")
    miss_es = [e for e in EFFECT_TYPES if e not in es]
    if miss_es:
        raise DataError("nn/weights.json.analyzer.effect_scales: нет масштаба для типов эффектов: "
                        + ", ".join(miss_es) + ".")
    cas = an[K_CASCADE]
    if not isinstance(cas, dict):
        raise DataError("nn/weights.json.analyzer.cascade: ожидался объект.")
    for ckey in (K_NETWORK_LINKS, K_MAX_DEPTH, K_DECAY):
        if ckey not in cas:
            raise DataError("nn/weights.json.analyzer.cascade: отсутствует ключ '" + str(ckey) + "'.")
    if not isinstance(cas[K_NETWORK_LINKS], dict):
        raise DataError("nn/weights.json.analyzer.cascade.network_links: ожидался объект.")
    if int(cas[K_MAX_DEPTH]) < 1:
        raise DataError("nn/weights.json.analyzer.cascade.max_depth: должно быть >= 1.")
    pm = an[K_PLAUS_MODEL]
    if not isinstance(pm, dict):
        raise DataError("nn/weights.json.analyzer.plausibility_model: ожидался объект.")
    for pkey in (K_PM_BASE, K_PM_TOP, K_PM_JITTER, K_PM_DRIFT, K_PM_OVERRIDE, K_PM_COMPLETENESS):
        if pkey not in pm:
            raise DataError("nn/weights.json.analyzer.plausibility_model: отсутствует ключ '" + str(pkey) + "'.")
    mm = an[K_MAG_MODEL]
    if not isinstance(mm, dict):
        raise DataError("nn/weights.json.analyzer.magnitude_model: ожидался объект.")
    for mkey in (K_MM_BASE, K_MM_TOP, K_MM_JITTER):
        if mkey not in mm:
            raise DataError("nn/weights.json.analyzer.magnitude_model: отсутствует ключ '" + str(mkey) + "'.")
    dr = an[K_DRIFT]
    if not isinstance(dr, dict) or K_D_BOUND not in dr or K_D_PENALTY not in dr:
        raise DataError("nn/weights.json.analyzer.drift: нужны ключи 'bound' и 'plaus_penalty'.")
    pr = an[K_PATCH_RULES]
    if not isinstance(pr, dict) or K_KEYWORD_MAP not in pr or K_DEFAULT_OPS not in pr:
        raise DataError("nn/weights.json.analyzer.patch_rules: нужны 'keyword_map' и 'default_ops'.")
    th = an[K_THRESHOLDS]
    if not isinstance(th, dict) or K_TH_MIN_PLAUS not in th or K_TH_AMBIGUITY not in th:
        raise DataError("nn/weights.json.analyzer.thresholds: нужны 'min_plausibility' и 'ambiguity_gap'.")
    temp = float(an[K_TEMPERATURE])
    if temp <= 0.0:
        raise DataError("nn/weights.json.analyzer.temperature: должно быть > 0 (получено " + str(temp) + ").")
    if not isinstance(an[K_REASON_FEATURES], dict):
        raise DataError("nn/weights.json.analyzer.reason_features: ожидался объект (признак -> ключ причины).")
    rm = an[K_ROLE_MAP]
    if not isinstance(rm, dict):
        raise DataError("nn/weights.json.analyzer.role_map: ожидался объект.")
    miss_rm = [r for r in ROLE_VALUES if r not in rm]
    if miss_rm:
        raise DataError("nn/weights.json.analyzer.role_map: нет веса для ролей: " + ", ".join(miss_rm) + ".")
    psm = an[K_PRISON_MAP]
    if not isinstance(psm, dict):
        raise DataError("nn/weights.json.analyzer.prison_severity_map: ожидался объект.")
    miss_psm = [p for p in PRISON_VALUES if p not in psm]
    if miss_psm:
        raise DataError("nn/weights.json.analyzer.prison_severity_map: нет severity для статусов: "
                        + ", ".join(miss_psm) + ".")
    lm = an[K_LAW_MODEL]
    if not isinstance(lm, dict):
        raise DataError("nn/weights.json.analyzer.law_model: ожидался объект.")
    for lkey in (K_PRED_POLARITY, K_PRED_BUDGET, K_ENF_BUDGET, K_COMPLETENESS_SLOTS):
        if lkey not in lm:
            raise DataError("nn/weights.json.analyzer.law_model: отсутствует ключ '" + str(lkey) + "'.")
    if not isinstance(lm[K_COMPLETENESS_SLOTS], list):
        raise DataError("nn/weights.json.analyzer.law_model.completeness_slots: ожидался массив имён слотов.")
    return an


# ================= извлечение признаков контекста (значения — из state, веса — из JSON) =================
def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _group_of(state: GameState, action: ActionData):
    gid = getattr(action, "target_group_id", "") or ""
    for g in state.groups:
        if g.id == gid:
            return g
    return state.groups[0] if state.groups else None


def _party_of(state: GameState, action: ActionData):
    pid = getattr(action, "target_group_id", "") or ""
    for p in state.parties:
        if p.id == pid:
            return p
    return None


def _candidate_of(state: GameState, action: ActionData):
    cid = getattr(action, "target_candidate_id", "") or ""
    for c in state.candidates:
        if c.id == cid:
            return c
    return None


def _extract_features(state: GameState, action: ActionData, an: Dict[str, Any]) -> Dict[str, float]:
    pl = state.player
    role_val = pl.role.value
    prison_val = pl.prison_status.value
    role_weight = float(an[K_ROLE_MAP].get(role_val, 0.0))
    prison_weight = float(an[K_PRISON_MAP].get(prison_val, 0.0))

    group = _group_of(state, action)
    party = _party_of(state, action)
    cand = _candidate_of(state, action)

    issue = getattr(action, "issue", "") or ""
    salience = 0.0
    if group is not None and issue and issue in group.issues:
        salience = _clamp01(float(group.issues[issue]) / SCALE)

    relationship = 0.0
    if party is not None:
        relationship = _clamp01(float(party.trust_to_player) / SCALE)
    elif group is not None:
        relationship = _clamp01(float(group.loyalty) / SCALE)

    fatigue = _clamp01((float(pl.stress) + float(pl.fatigue)) / (2.0 * SCALE))

    history_repeat = 0.0
    aid = getattr(action, "id", "") or ""
    for qa in state.week_actions:
        if qa.get("action_id") == aid:
            history_repeat = 1.0
            break

    intent = getattr(action, "intent", "") or ""
    aggression = 1.0 if intent == "attack" else 0.0
    secret = bool(getattr(action, "secret", False))
    illegality = float(getattr(action, "illegality", 0.0) or 0.0)
    secrecy = _clamp01((1.0 if secret else 0.0) * illegality)
    risk_norm = _clamp01(float(getattr(action, "risk", 0) or 0) / SCALE)

    target_size_norm = 0.0
    if group is not None:
        sizes = [float(g.size) for g in state.groups] or [1.0]
        max_size = max(sizes) or 1.0
        target_size_norm = _clamp01(float(group.size) / max_size)

    mood_baseline = _clamp01(float(group.mood) / SCALE) if group is not None else 0.0
    loyalty_baseline = _clamp01(float(group.loyalty) / SCALE) if group is not None else 0.0
    trust_norm = _clamp01(float(pl.trust) / SCALE)
    anti_norm = _clamp01(float(pl.anti_awareness) / SCALE)
    scandal_norm = _clamp01(float(cand.scandal) / SCALE) if cand is not None else 0.0

    total_seats = sum(int(v) for v in state.parliament_seats.values()) or 1
    seats_norm = _clamp01(float(state.council_seats) / float(total_seats))

    active_promises = [p for p in state.promises if p.get("status") == "active"]
    expiring = [p for p in active_promises if int(p.get("deadline_week", 0)) <= state.week + 2]
    promise_pressure = _clamp01(float(len(expiring)) / float(max(1, len(active_promises))))

    institutional = 1.0 if intent in ("bill", "coalition", "veto", "party") else 0.0
    fresh_fact = 1.0 if any(int(c.get("week", 0)) == state.week for c in state.clippings) else 0.0

    return {
        "role_weight": role_weight,
        "prison_weight": prison_weight,
        "salience": salience,
        "relationship": relationship,
        "fatigue": fatigue,
        "history_repeat": history_repeat,
        "aggression": aggression,
        "secrecy": secrecy,
        "risk_norm": risk_norm,
        "target_size_norm": target_size_norm,
        "mood_baseline": mood_baseline,
        "loyalty_baseline": loyalty_baseline,
        "trust_norm": trust_norm,
        "anti_norm": anti_norm,
        "scandal_norm": scandal_norm,
        "seats_norm": seats_norm,
        "promise_pressure": promise_pressure,
        "institutional": institutional,
        "fresh_fact": fresh_fact,
    }


# ================= softmax / распределение / магнитуда =================
def _softmax(scores: Dict[str, float], temperature: float) -> Dict[str, float]:
    if not scores:
        return {}
    items = list(scores.items())
    mx = max(v for _, v in items)
    exps = {k: math.exp((v - mx) / temperature) for k, v in items}
    total = sum(exps.values())
    if total <= 0.0:
        n = float(len(items))
        return {k: 1.0 / n for k, _ in items}
    return {k: exps[k] / total for k in exps}


def _round_step(x: float, step: float = 0.05) -> float:
    return round(round(x / step) * step, 2)


def _context_positivity(feat: Dict[str, float], an: Dict[str, Any]) -> float:
    fw = an[K_FEATURE_WEIGHTS]
    s = 0.0
    for name in ANALYZER_FEATURES:
        s += float(fw.get(name, 0.0)) * float(feat.get(name, 0.0))
    return s


def _distribution(tier: str, feat: Dict[str, float], an: Dict[str, Any],
                  rng: random.Random) -> Dict[str, float]:
    priors = an[K_TIER_PRIORS]
    positivity = _context_positivity(feat, an)
    jitter = float(an[K_PLAUS_MODEL][K_PM_JITTER])
    scores: Dict[str, float] = {}
    for t in TIERS:
        base = float(priors.get(t, 0.0))
        base += positivity * float(TIER_SIGN.get(t, 0))
        base += float(t == tier) * 0.5
        base += rng.uniform(-jitter, jitter)
        scores[t] = base
    dist = _softmax(scores, float(an[K_TEMPERATURE]))
    dist = {t: _round_step(dist.get(t, 0.0)) for t in TIERS}
    diff = round(1.0 - sum(dist.values()), 2)
    if abs(diff) >= 0.01:
        top = max(dist, key=lambda k: dist[k])
        dist[top] = _round_step(dist[top] + diff)
    return dist


def _magnitude(an: Dict[str, Any], top_prob: float, rng: random.Random) -> int:
    mm = an[K_MAG_MODEL]
    mag = float(mm[K_MM_BASE]) + float(mm[K_MM_TOP]) * top_prob
    mag += rng.uniform(-float(mm[K_MM_JITTER]), float(mm[K_MM_JITTER]))
    return max(1, int(round(mag)))


def _reason_key(feat: Dict[str, float], an: Dict[str, Any]) -> str:
    rf = an[K_REASON_FEATURES]
    best_key = "luck"
    best_val = -1e9
    for name, key in rf.items():
        v = float(feat.get(name, 0.0))
        if v > best_val:
            best_val = v
            best_key = str(key)
    return best_key


# ================= эффекты + каскад (одна ступень в прототипе) =================
def _primary_effects(state: GameState, action: ActionData, tier: str, mag: int,
                     an: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str, str]]]:
    es = an[K_EFFECT_SCALES]
    sign = TIER_SIGN.get(tier, 0)
    effects: List[Dict[str, Any]] = []
    reactors: List[Tuple[str, str, str]] = []  # (kind, id, name)
    group = _group_of(state, action)
    if group is not None and sign != 0:
        effects.append({"type": "group_mood", "group": group.id,
                        "delta": sign * mag * int(round(float(es["group_mood"])))})
        effects.append({"type": "group_loyalty", "group": group.id,
                        "delta": sign * mag * int(round(float(es["group_loyalty"])))})
        effects.append({"type": "support", "group": group.id, "kind": "candidate",
                        "subject": state.player.name,
                        "delta": sign * mag * int(round(float(es["support"])))})
        reactors.append(("group", group.id, group.name))
    pl = state.player
    if sign > 0:
        ps = int(round(float(es["player_stat"])))
        effects.append({"type": "player_stat", "stat": "awareness", "delta": mag * ps})
        effects.append({"type": "player_stat", "stat": "trust", "delta": max(1, mag - 1) * ps})
    elif sign < 0:
        ps = int(round(float(es["player_stat"])))
        effects.append({"type": "player_stat", "stat": "anti_awareness", "delta": mag * ps})
    intent = getattr(action, "intent", "") or ""
    if intent == "attack":
        ps = int(round(float(es["player_stat"])))
        effects.append({"type": "player_stat", "stat": "threat", "delta": mag * ps})
        cand = _candidate_of(state, action)
        if cand is not None:
            effects.append({"type": "support", "group": (group.id if group else ""),
                            "kind": "candidate", "subject": cand.name,
                            "delta": -sign * mag * int(round(float(es["support"])))})
            reactors.append(("candidate", cand.id, cand.name))
    return effects, reactors


def _cascade_effects(state: GameState, effects: List[Dict[str, Any]],
                     reactors: List[Tuple[str, str, str]], mag: int, sign: int,
                     an: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str, str]]]:
    cas = an[K_CASCADE]
    links = cas[K_NETWORK_LINKS]
    decay = float(cas[K_DECAY])
    es = an[K_EFFECT_SCALES]
    sec_effects: List[Dict[str, Any]] = []
    sec_reactors: List[Tuple[str, str, str]] = []
    seen = set((k, i) for k, i, _ in reactors)
    for kind, rid, _name in list(reactors):
        neighbors = links.get(kind + ":" + rid, []) or []
        for nb in neighbors:
            if ":" not in nb:
                continue
            nkind, nid = nb.split(":", 1)
            if (nkind, nid) in seen:
                continue
            seen.add((nkind, nid))
            d2 = int(round(sign * mag * decay))
            if nkind == "group":
                g = next((x for x in state.groups if x.id == nid), None)
                if g is not None:
                    sec_effects.append({"type": "group_mood", "group": g.id,
                                        "delta": d2 * int(round(float(es["group_mood"])))})
                    sec_reactors.append(("group", g.id, g.name))
            elif nkind == "party":
                p = next((x for x in state.parties if x.id == nid), None)
                if p is not None:
                    sec_effects.append({"type": "support", "group": "", "kind": "party",
                                        "subject": p.name,
                                        "delta": d2 * int(round(float(es["support"])))})
                    sec_reactors.append(("party", p.id, p.name))
            elif nkind == "npc":
                n = next((x for x in state.npcs if x.id == nid), None)
                if n is not None:
                    sec_reactors.append(("npc", n.id, n.name))
            elif nkind == "publication":
                pb = next((x for x in state.publications if x.id == nid), None)
                if pb is not None:
                    sec_reactors.append(("publication", pb.id, pb.name))
    return sec_effects, sec_reactors


def _plausibility(an: Dict[str, Any], top_prob: float, completeness: float,
                  rng: random.Random) -> float:
    pm = an[K_PLAUS_MODEL]
    val = float(pm[K_PM_BASE])
    val += float(pm[K_PM_TOP]) * top_prob
    val += float(pm[K_PM_COMPLETENESS]) * completeness
    val += rng.uniform(-float(pm[K_PM_JITTER]), float(pm[K_PM_JITTER]))
    return round(max(0.0, min(1.0, val)), 2)


# ================= сборка скрипта =================
def _build_script(state: GameState, action: ActionData, tier: str, rng: random.Random,
                  an: Dict[str, Any], completeness: float) -> Dict[str, Any]:
    feat = _extract_features(state, action, an)
    dist = _distribution(tier, feat, an, rng)
    top_prob = max(dist.values()) if dist else 0.0
    mag = _magnitude(an, top_prob, rng)
    sign = TIER_SIGN.get(tier, 0)
    effects, reactors = _primary_effects(state, action, tier, mag, an)
    sec_effects, sec_reactors = _cascade_effects(state, effects, reactors, mag, sign, an)
    all_effects = effects + sec_effects
    all_reactors = reactors + sec_reactors
    # реакторы-имена для ui (list[str]); имена приходят из state (данные мира), не вшиваются
    reactor_names: List[str] = []
    seen_names = set()
    for _k, _i, nm in all_reactors:
        if nm and nm not in seen_names:
            seen_names.add(nm)
            reactor_names.append(nm)
    if state.publications and state.publications[0].name not in seen_names:
        reactor_names.append(state.publications[0].name)
    polarity = _round_step(sign * min(1.0, mag / 3.0))
    intensity = _round_step(min(1.0, mag / 3.0))
    reason = _reason_key(feat, an)
    plaus = _plausibility(an, top_prob, completeness, rng)
    min_plaus = float(an[K_THRESHOLDS][K_TH_MIN_PLAUS])
    if plaus < min_plaus:
        # низкоправдоподобный исход: смягчаем знак к нейтрали (структурно, без слов)
        polarity = _round_step(polarity * 0.5)
        intensity = _round_step(intensity * 0.5)
    primary = str(getattr(action, "title", "")) + ": " + str(tier)
    return {
        K_PRIMARY: primary,
        K_SECONDARY: [],
        K_REACTORS: reactor_names,
        K_TONE: polarity,
        K_TONE_VECTOR: {K_POLARITY: polarity, K_INTENSITY: intensity},
        K_TIER_DISTRIBUTION: dist,
        K_REASON_KEY: reason,
        K_EFFECTS: all_effects,
        K_PLAUSIBILITY: plaus,
        K_DELAYED: [],
    }


# ================= публичные входы (контракты systems.py) =================
def analyze_action(state: GameState, action: ActionData, tier: str,
                   rng: random.Random) -> Dict[str, Any]:
    an = _weights_analyzer(state_data_holder[0]) if state_data_holder else _weights_analyzer_from_state(state)
    return _build_script(state, action, tier, rng, an, completeness=1.0)


# nn_analyzer не получает data напрямую в analyze_action (сигнатура systems), поэтому
# держим ссылку на GameData, установленную при первом вызове с data, либо читаем из state.
# Чтобы не ломать контракт systems (analyze_action(state, action, tier, rng) без data),
# валидатор весов берёт data из module-level holder, который main/Systems инициализирует
# через set_data(); если holder пуст — fallback на чтение weights из state невозможен,
# поэтому бросаем адресную ошибку (R1: НС-анализатор требует data).
state_data_holder: List[Optional[GameData]] = [None]


def set_data(data: GameData) -> None:
    state_data_holder[0] = data


def _weights_analyzer_from_state(state: GameState) -> Dict[str, Any]:  # pragma: no cover
    raise DataError("nn_analyzer: GameData не установлен (set_data не вызван). "
                    "НС-анализатор не может прочитать веса без ссылки на данные.")


def analyze_law_forecast(state: GameState, law: Dict[str, Any],
                         rng: random.Random) -> Dict[str, Any]:
    an = _resolve_an()
    lm = an[K_LAW_MODEL]
    skeleton = law.get(K_SKELETON, {}) or {}
    predicate = str(skeleton.get(K_PREDICATE, ""))
    objects = skeleton.get(K_OBJECTS, []) or []
    enforcement = str(skeleton.get(K_ENFORCEMENT, ""))
    budget = str(skeleton.get(K_BUDGET, ""))

    slots = lm[K_COMPLETENESS_SLOTS] or []
    filled = 0
    for s in slots:
        sval = str(s)
        if sval == K_PREDICATE and predicate:
            filled += 1
        elif sval == K_OBJECTS and objects:
            filled += 1
        elif sval == K_ENFORCEMENT and enforcement and enforcement != "нет":
            filled += 1
        elif sval == K_BUDGET and budget and budget != "нет":
            filled += 1
    completeness = _clamp01(float(filled) / float(max(1, len(slots))))

    pol_map = lm[K_PRED_POLARITY]
    sign = int(pol_map.get(predicate, 0))
    es = an[K_EFFECT_SCALES]
    mag = _magnitude(an, completeness, rng)
    effects: List[Dict[str, Any]] = []
    reactor_names: List[str] = []
    seen = set()
    for obj in objects:
        g = next((x for x in state.groups if x.id == obj), None)
        if g is None:
            continue
        if g.name not in seen:
            seen.add(g.name)
            reactor_names.append(g.name)
        if sign != 0:
            effects.append({"type": "group_mood", "group": g.id,
                            "delta": sign * mag * int(round(float(es["group_mood"])))})
            effects.append({"type": "support", "group": g.id, "kind": "candidate",
                            "subject": state.player.name,
                            "delta": sign * mag * int(round(float(es["support"])))})
    pred_budget = lm[K_PRED_BUDGET]
    if predicate in pred_budget:
        effects.append({"type": "treasury", "delta": int(pred_budget[predicate])})
    enf_budget = lm[K_ENF_BUDGET]
    if enforcement in enf_budget:
        effects.append({"type": "treasury", "delta": int(enf_budget[enforcement])})
    if budget in pred_budget:
        effects.append({"type": "treasury", "delta": int(pred_budget[budget])})

    tier = "solid" if sign > 0 else ("minor" if sign < 0 else "complication")
    dist = _distribution(tier, {n: 0.0 for n in ANALYZER_FEATURES}, an, rng)
    top_prob = max(dist.values()) if dist else 0.0
    polarity = _round_step(sign * min(1.0, mag / 3.0))
    intensity = _round_step(min(1.0, mag / 3.0))
    plaus = _plausibility(an, top_prob, completeness, rng)
    primary = str(law.get(K_TITLE, "")) + ": forecast " + str(predicate)
    return {
        K_PRIMARY: primary,
        K_SECONDARY: [],
        K_REACTORS: reactor_names,
        K_TONE: polarity,
        K_TONE_VECTOR: {K_POLARITY: polarity, K_INTENSITY: intensity},
        K_TIER_DISTRIBUTION: dist,
        K_REASON_KEY: "context",
        K_EFFECTS: effects,
        K_PLAUSIBILITY: plaus,
        K_DELAYED: [],
    }


def produce_actual(script: Dict[str, Any], _unused: Any,
                   rng: random.Random) -> Dict[str, Any]:
    an = _resolve_an()
    dr = an[K_DRIFT]
    bound = int(dr[K_D_BOUND])
    penalty = float(dr[K_D_PENALTY])
    actual = copy.deepcopy(script)
    total_drift = 0
    cnt = 0
    for eff in actual.get(K_EFFECTS, []) or []:
        if K_EFF_DELTA in eff:
            d = rng.randint(-bound, bound)
            eff[K_EFF_DELTA] = int(eff[K_EFF_DELTA]) + d
            total_drift += abs(d)
            cnt += 1
    avg_drift = (float(total_drift) / float(cnt)) if cnt else 0.0
    new_plaus = float(actual.get(K_PLAUSIBILITY, 0.0)) - penalty * avg_drift
    actual[K_PLAUSIBILITY] = round(max(0.0, min(1.0, new_plaus)), 2)
    actual[K_IS_ACTUAL] = True
    actual[K_DELAYED] = []
    return actual


def patch_script(script: Dict[str, Any], correction: str,
                 state: GameState) -> Tuple[Dict[str, Any], bool]:
    an = _resolve_an()
    pr = an[K_PATCH_RULES]
    kmap = pr[K_KEYWORD_MAP] or {}
    default_ops = pr[K_DEFAULT_OPS] or {}
    patched = copy.deepcopy(script)
    applied = False
    corr = (correction or "").strip().lower()
    ops: Dict[str, Any] = {}
    if corr:
        for word, wops in kmap.items():
            if str(word).lower() in corr:
                ops = dict(wops) if isinstance(wops, dict) else {}
                applied = True
                break
        if not ops and isinstance(default_ops, dict) and default_ops:
            ops = dict(default_ops)
            applied = True
        patched[K_PLAYER_CORRECTION] = correction
        patched[K_PLAYER_OVERRIDE] = True
        applied = True
    if ops:
        patched = _apply_ops(patched, ops)
    return patched, bool(applied)


# ================= применение операций патча (структурно, без слов) =================
def _apply_ops(script: Dict[str, Any], ops: Dict[str, Any]) -> Dict[str, Any]:
    if bool(ops.get("flip_polarity", False)):
        for eff in script.get(K_EFFECTS, []) or []:
            if K_EFF_DELTA in eff:
                eff[K_EFF_DELTA] = -int(eff[K_EFF_DELTA])
        tv = script.get(K_TONE_VECTOR, {}) or {}
        if K_POLARITY in tv:
            tv[K_POLARITY] = -float(tv[K_POLARITY])
        if K_INTENSITY in tv:
            tv[K_INTENSITY] = float(tv[K_INTENSITY])
        script[K_TONE] = float(tv.get(K_POLARITY, script.get(K_TONE, 0.0)))
        script[K_TIER_DISTRIBUTION] = _mirror_distribution(script.get(K_TIER_DISTRIBUTION, {}) or {})
    scale = ops.get("magnitude_scale", None)
    if scale is not None:
        sc = float(scale)
        for eff in script.get(K_EFFECTS, []) or []:
            if K_EFF_DELTA in eff:
                eff[K_EFF_DELTA] = int(round(float(eff[K_EFF_DELTA]) * sc))
        tv = script.get(K_TONE_VECTOR, {}) or {}
        if K_INTENSITY in tv:
            tv[K_INTENSITY] = _round_step(float(tv[K_INTENSITY]) * sc)
    remove_types = ops.get("remove_effect_type", []) or []
    if remove_types:
        rt = set(str(x) for x in remove_types)
        script[K_EFFECTS] = [e for e in (script.get(K_EFFECTS, []) or [])
                             if e.get(K_EFF_TYPE) not in rt]
    shift = ops.get("tone_shift", None)
    if shift is not None:
        tv = script.get(K_TONE_VECTOR, {}) or {}
        new_pol = _clamp01sym(float(tv.get(K_POLARITY, 0.0)) + float(shift))
        tv[K_POLARITY] = _round_step(new_pol)
        script[K_TONE_VECTOR] = tv
        script[K_TONE] = float(tv[K_POLARITY])
    return script


def _clamp01sym(x: float) -> float:
    return max(-1.0, min(1.0, x))


def _mirror_distribution(dist: Dict[str, float]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for t in TIERS:
        out[t] = float(dist.get(TIER_MIRROR.get(t, t), 0.0))
    total = sum(out.values()) or 1.0
    return {t: _round_step(out[t] / total) for t in TIERS}


# ================= резолв секции analyzer с holder-фолбэком =================
def _resolve_an() -> Dict[str, Any]:
    data = state_data_holder[0] if state_data_holder else None
    if data is None:
        raise DataError("nn_analyzer: GameData не установлен (set_data не вызван). "
                        "НС-анализатор не может прочитать веса без ссылки на данные.")
    return _weights_analyzer(data)