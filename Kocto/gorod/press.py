"""Газеты пишут о фактах недели, а не «о городских делах».

Каждая газета выбирает факт по своей повестке, угол (pro/contra/neutral) — по своему
отношению к актору и исходу, шаблон — наименее использованный в этой кампании.
"""
from __future__ import annotations

import random
from typing import Dict, List

from .engine import DataError, Fact, State


REPEAT_WEEKS = 2


def _angle(state: State, data: dict, paper_id: str, fact: Fact) -> str:
    p = data["papers"][paper_id]
    bias = p["bias_player"] if fact.actor == "player" else p["bias_rival"]
    if p.get("editor") and fact.actor == "player":
        bias += (state.npc_loyalty[p["editor"]] - 50) / 100.0
    score = 0.5 * fact.outcome + bias
    return "pro" if score > 0.3 else ("contra" if score < -0.3 else "neutral")


def _interest(data: dict, paper_id: str, fact: Fact) -> float:
    p = data["papers"][paper_id]
    bias = p["bias_player"] if fact.actor == "player" else p["bias_rival"]
    # газете интересно то, что подтверждает её взгляд: хорошее о «своих», плохое о «чужих»
    return 1.0 + (0.5 if bias * fact.outcome > 0 else 0.0)


def _pick_group(fact: Fact, sign: int) -> str:
    if fact.group:
        return fact.group
    best, val = "", 0.0
    for key, d in fact.deltas.items():
        gid, kind = key.split(".")
        if kind == "support" and d * sign > val:
            best, val = gid, d * sign
    return best


def _lru(state: State, keys: List[str], rng: random.Random) -> str:
    low = min(state.press_used.get(k, -1) for k in keys)
    pool = sorted(k for k in keys if state.press_used.get(k, -1) == low)
    return rng.choice(pool)


def _voice(state: State, data: dict, gid: str, mood: str, slots: Dict[str, str], rng: random.Random) -> str:
    if not gid:
        return ""
    lines = data["groups"][gid]["voices"][mood]
    keys = ["v:" + gid + ":" + mood + ":" + str(i) for i in range(len(lines))]
    key = _lru(state, keys, rng)
    state.press_used[key] = state.week
    return _fill(lines[int(key.rsplit(":", 1)[1])], slots, "voice " + key)


def _fill(template: str, slots: Dict[str, str], where: str) -> str:
    try:
        text = template.format_map(slots)
    except KeyError as exc:
        raise DataError("шаблон " + where + ": нет данных для слота " + str(exc)) from exc
    return text[:1].upper() + text[1:] if text else text


def _slots(state: State, data: dict, fact: Fact) -> Dict[str, str]:
    rv = data["rival"]
    s = {"player": state.player_name, "rival": rv["forms"]["im"], "rival_title": rv["title"],
         "week": str(fact.week)}
    s.update(data["press"]["gender"][state.gender])
    for case, val in rv["forms"].items():
        s["rival_" + case] = val
    if fact.proposal:
        for case, val in data["proposals"][fact.proposal]["forms"].items():
            s["prop_" + case] = val
        if fact.side in (-1, 1):
            side = data["sides"][str(fact.side)]
            s["side_pos"] = side["pos"].format_map(s)
            s["side_goal"] = side["goal"].format_map(s)
            s["decision"] = data["press"]["decision_words"][str(fact.side)]
    if fact.paper:
        for case, val in data["papers"][fact.paper]["forms"].items():
            s["paper_" + case] = val
        s["paper"] = s["paper_im"]
    enemy = fact.extra.get("enemy")
    if enemy:
        for case, val in data["enemies"][enemy]["forms"].items():
            s["enemy_" + case] = val
    for key in ("deadline", "made_week", "pv", "rv", "weeks", "reason", "level"):
        if key in fact.extra:
            s[key] = str(fact.extra[key])
    if "won" in fact.extra:
        s["result"] = data["press"]["result_words"]["win" if fact.extra["won"] else "loss"]
    return s


def render(state: State, data: dict, paper_id: str, fact: Fact, rng: random.Random) -> dict:
    angle = _angle(state, data, paper_id, fact)
    kinds = data["press"]["kinds"][fact.kind]
    by_id = {t["id"]: t for t in kinds if t["angle"] == angle}
    tid = _lru(state, list(by_id), rng)
    if state.press_used.get(tid, -99) >= state.week - REPEAT_WEEKS and angle != "neutral":
        # все шаблоны своего угла свежие — газета пишет сдержаннее, но не повторяется
        neutral = {t["id"]: t for t in kinds if t["angle"] == "neutral"}
        alt = _lru(state, list(neutral), rng)
        if state.press_used.get(alt, -99) < state.press_used.get(tid, -99):
            by_id, tid, angle = neutral, alt, "neutral"
    state.press_used[tid] = state.week
    t = by_id[tid]
    s = _slots(state, data, fact)
    g_main = _pick_group(fact, 1 if fact.outcome >= 0 else -1) or _pick_group(fact, -1)
    for prefix, gid in (("group", g_main),):
        if gid:
            for case, val in data["groups"][gid]["forms"].items():
                s[prefix + "_" + case] = val
    gp, ga = _pick_group(fact, 1), _pick_group(fact, -1)
    need = t["headline"] + t["lead"]
    if "{voice_pleased}" in need:
        s["voice_pleased"] = _voice(state, data, gp, "pleased", s, rng)
    if "{voice_angry}" in need:
        s["voice_angry"] = _voice(state, data, ga, "angry", s, rng)
    if "{voice_main}" in need:
        main = gp if (fact.outcome >= 0 and gp) else ga
        s["voice_main"] = _voice(state, data, main, "pleased" if main == gp and main else "angry", s, rng)
    return {"paper": paper_id, "paper_name": data["papers"][paper_id]["forms"]["im"], "fact_id": fact.id,
            "angle": angle, "template": tid, "headline": _fill(t["headline"], s, tid),
            "lead": _fill(t["lead"], s, tid).strip()}


def _stale(state: State, data: dict, pid: str, f: Fact) -> bool:
    """Все подходящие шаблоны свежие — заметка повторила бы недавнюю; газета предпочтёт другой факт."""
    angle = _angle(state, data, pid, f)
    ids = [t["id"] for t in data["press"]["kinds"][f.kind] if t["angle"] in (angle, "neutral")]
    return min(state.press_used.get(t, -99) for t in ids) >= state.week - REPEAT_WEEKS


def write_week(state: State, data: dict, facts: List[Fact], rng: random.Random) -> List[dict]:
    out, taken = [], set()
    if not facts:
        return out
    for pid in sorted(data["papers"]):
        def score(f: Fact) -> float:
            base = (100.0 if f.kind in ("election", "death") else f.magnitude) * _interest(data, pid, f)
            return base * (0.3 if f.id in taken else 1.0) * (0.3 if _stale(state, data, pid, f) else 1.0)
        fact = max(facts, key=lambda f: (score(f), f.id))
        taken.add(fact.id)
        out.append(render(state, data, pid, fact, rng))
    return out
