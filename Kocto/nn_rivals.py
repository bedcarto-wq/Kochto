"""ИИ соперников: один общий скорер-политика для всех кандидатов-оппонентов.

Самописный, детерминированный (rng недели), только stdlib. Слова и числа — из data/world/world.json
(секция rivals); здесь только математика выбора хода. Разнообразие даёт не модель, а вход:
личность из JSON + положение в гонке + память о действиях игрока.

Цикл: в конце недели execute() исполняет ходы, запланированные неделю назад, затем plan()
выбирает ходы на следующую неделю. Планы лежат в state.world["rival_plans"] — их можно
разведать (тег intel или действие «собрать слухи»).
"""
from __future__ import annotations

import random
from typing import Any, Callable, Dict, List, Optional


def available() -> bool:
    return True


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def player_score(state: Any) -> int:
    pl = state.player
    return int(pl.awareness + pl.trust - pl.anti_awareness)


def rival_score(cand: Any) -> int:
    return int(cand.popularity - cand.scandal)


def _personality(cfg: Dict[str, Any], cand_id: str) -> Dict[str, float]:
    base = dict(cfg.get("default_personality") or {})
    base.update((cfg.get("personalities") or {}).get(cand_id, {}) or {})
    return {k: float(v) for k, v in base.items()}


def _memory(state: Any, cand_id: str) -> Dict[str, Any]:
    mem = state.world.setdefault("rival_memory", {})
    return mem.setdefault(cand_id, {"attacked": 0, "last_move": "", "moves": 0})


def features(state: Any, cand: Any) -> Dict[str, float]:
    mine = rival_score(cand)
    others = [rival_score(c) for c in state.candidates if c.id != cand.id] + [player_score(state)]
    leader = max(others + [mine])
    weeks_left = max(0, int(state.next_election_week) - int(state.week))
    mem = _memory(state, cand.id)
    return {
        "behind": _clamp((leader - mine) / 30.0, 0.0, 1.0),
        "player_leads": _clamp((player_score(state) - mine + 10) / 30.0, 0.0, 1.0),
        "urgency": _clamp(1.0 - weeks_left / 10.0, 0.0, 1.0),
        "revenge": _clamp(float(mem.get("attacked", 0)) / 3.0, 0.0, 1.0),
        "scandal": _clamp(cand.scandal / 30.0, 0.0, 1.0),
    }


def utility(move: Dict[str, Any], feats: Dict[str, float], pers: Dict[str, float]) -> float:
    u = float(move.get("base", 0.0))
    for key, w in (move.get("weights") or {}).items():
        val = feats.get(key, pers.get(key, 0.0))
        u += float(w) * float(val)
    return u


def _pick_group(state: Any, cand: Any, rng: random.Random) -> Optional[Any]:
    best = None
    best_val = -1.0
    for g in state.groups:
        have = float(g.candidate_support.get(cand.name, 0))
        room = max(0.0, float(g.size) - have)
        heat = max(list((g.issues or {}).values()) or [50]) / 100.0
        val = room * (0.5 + heat) * rng.uniform(0.85, 1.15)
        if val > best_val:
            best, best_val = g, val
    return best


def _top_issue(group: Any) -> str:
    issues = getattr(group, "issues", None) or {}
    if not issues:
        return ""
    return max(sorted(issues), key=lambda k: issues[k])


def plan(state: Any, cfg: Dict[str, Any], rng: random.Random) -> Dict[str, Dict[str, Any]]:
    moves = cfg.get("moves") or {}
    if not moves or not state.candidates:
        state.world["rival_plans"] = {}
        return {}
    scored: List[Any] = []
    for cand in state.candidates:
        pers = _personality(cfg, cand.id)
        feats = features(state, cand)
        options = []
        for mid in sorted(moves):
            u = utility(moves[mid], feats, pers) + rng.uniform(0.0, 0.3)
            options.append((u, mid))
        options.sort(reverse=True)
        u, mid = options[0]
        g = _pick_group(state, cand, rng)
        scored.append((u, cand.id, {"move": mid, "group": g.id if g else "",
                                    "issue": _top_issue(g) if g else "", "utility": round(u, 2),
                                    "why": _explain(feats, pers, moves[mid])}))
    scored.sort(key=lambda x: x[0], reverse=True)
    cap = int(cfg.get("max_moves_per_week", 3))
    plans = {cid: p for _u, cid, p in scored[:cap]}
    state.world["rival_plans"] = plans
    return plans


def _explain(feats: Dict[str, float], pers: Dict[str, float], move: Dict[str, Any]) -> str:
    parts = []
    for key, w in sorted((move.get("weights") or {}).items(), key=lambda kv: -abs(float(kv[1]))):
        val = feats.get(key, pers.get(key, 0.0))
        parts.append(key + "=" + str(round(float(val), 2)))
    return ", ".join(parts[:3])


def describe(cfg: Dict[str, Any], move_id: str) -> str:
    return str(((cfg.get("moves") or {}).get(move_id) or {}).get("label", move_id))


def execute(state: Any, cfg: Dict[str, Any], rng: random.Random,
            push_story: Callable[..., Any], issue_name: Callable[[str], str]) -> List[str]:
    """Исполнить планы прошлой недели. Возвращает строки для журнала."""
    plans = dict(state.world.get("rival_plans") or {})
    moves = cfg.get("moves") or {}
    logs: List[str] = []
    for cand in state.candidates:
        p = plans.get(cand.id)
        if not p:
            continue
        move = moves.get(p.get("move", ""))
        if not move:
            continue
        group = None
        for g in state.groups:
            if g.id == p.get("group"):
                group = g
        eff = dict(move.get("effects") or {})
        caught = False
        if "caught_chance" in move and rng.random() < float(move["caught_chance"]):
            caught = True
            for k, v in (move.get("caught_effects") or {}).items():
                eff[k] = eff.get(k, 0) + v
        _apply(state, cand, group, eff, float(cfg.get("popularity_diminish", 0.0)))
        mem = _memory(state, cand.id)
        mem["last_move"] = p.get("move", "")
        mem["moves"] = int(mem.get("moves", 0)) + 1
        if p.get("move") in ("attack_player", "dirty_trick"):
            mem["attacked"] = max(0, int(mem.get("attacked", 0)) - 1)   # месть «выпущена»
        pub = rng.choice(state.publications) if state.publications else None
        slots = {"rival": cand.name, "player": state.player.name,
                 "group": group.name if group else "горожане",
                 "issue": issue_name(p.get("issue", "")) or "городские дела",
                 "publication": pub.name if pub else "Городской вестник"}
        tone = -0.4 if p.get("move") in ("attack_player", "dirty_trick") else 0.2
        push_story(state, slots["publication"], _fmt(move.get("headline", ""), slots),
                   _fmt(move.get("body", ""), slots), tone, "rival")
        if caught:
            push_story(state, slots["publication"], _fmt("Штаб кандидата {rival} уличён в грязной игре", slots),
                       _fmt("Журналисты выяснили, кто стоит за ночными листовками. Следы ведут в штаб: {rival}.", slots),
                       -0.6, "rival")
        logs.append(cand.name + ": " + describe(cfg, p.get("move", "")) + (" (уличён)" if caught else ""))
    return logs


def _fmt(tpl: str, slots: Dict[str, Any]) -> str:
    try:
        return str(tpl).format(**slots)
    except (KeyError, IndexError, ValueError):
        return str(tpl)


def _apply(state: Any, cand: Any, group: Any, eff: Dict[str, Any], dim: float = 0.0) -> None:
    pl = state.player
    for key, v in eff.items():
        v = int(v)
        if key == "rival_popularity" and v > 0 and dim > 0:
            v = max(1 if cand.popularity < 100 else 0, min(v, int(round(v * (100 - cand.popularity) / 100.0 * dim))))
        if key == "rival_popularity":
            cand.popularity = int(_clamp(cand.popularity + v, 0, 100))
        elif key == "rival_scandal":
            cand.scandal = int(_clamp(cand.scandal + v, 0, 100))
        elif key == "rival_support" and group is not None:
            cur = int(group.candidate_support.get(cand.name, 0))
            group.candidate_support[cand.name] = int(_clamp(cur + v, 0, group.size))
        elif key == "player_anti":
            if v > 0 and dim > 0:
                v = max(1 if pl.anti_awareness < 100 else 0,
                        min(v, int(round(v * (100 - pl.anti_awareness) / 100.0 * dim))))
            pl.anti_awareness = int(_clamp(pl.anti_awareness + v, 0, 100))
        elif key == "player_trust":
            pl.trust = int(_clamp(pl.trust + v, 0, 100))
        elif key == "player_threat":
            pl.threat = int(_clamp(pl.threat + v, 0, 100))
