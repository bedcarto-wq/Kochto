"""ИИ соперника: планировщик по полезности.

Каждую неделю Ложкин перебирает возможные ходы, для каждого моделирует, как изменится
прогноз выборов (голоса соперника минус голоса кандидата), и выбирает лучший.
Ходы: встреча с группой, напоминание о «грехах» кандидата (из журнала фактов),
перехват популярной позиции, а если он проигрывает к концу кампании — грязные методы
(компромат или давление). Причина выбора сохраняется в факте (extra['why']).
"""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from typing import Dict, List

from .engine import STOLEN_CREDIT


@dataclass
class Option:
    kind: str  # meet | attack | steal | compromat | threat
    value: float
    group: str = ""
    proposal: str = ""
    side: int = 0
    about: str = ""
    why: str = ""
    deltas: Dict[str, Dict[str, float]] = field(default_factory=dict)


def margin(groups, data: dict) -> float:
    """Прогноз (без шума): голоса соперника минус голоса кандидата."""
    tv = float(data["tuning"]["trust_vote_base"])
    m = 0.0
    for gid, g in groups.items():
        gd = data["groups"][gid]
        voters = gd["size"] * gd["turnout"]
        ep = g.support_player * (tv + g.trust / 100.0)
        tot = ep + g.support_rival
        share = ep / tot if tot > 0 else 0.5
        m += voters * (1 - 2 * share)
    return m


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


def _simulate(state, data: dict, deltas: Dict[str, Dict[str, float]]) -> float:
    groups = copy.deepcopy(state.groups)
    zs = float(data["tuning"]["zero_sum"])
    for gid, d in deltas.items():
        g = groups[gid]
        sup, riv = d.get("support", 0.0), d.get("rival", 0.0)
        sup, riv = sup - zs * max(riv, 0.0), riv - zs * max(sup, 0.0)  # как engine._apply
        g.support_player = _clamp(g.support_player + sup)
        g.support_rival = _clamp(g.support_rival + riv)
        g.trust = _clamp(g.trust + d.get("trust", 0.0))
    return margin(groups, data) - margin(state.groups, data)


def _sins(state, data: dict):
    rv = data["rival"]
    since = state.week - int(rv["attack_memory_weeks"])
    return [f for f in state.facts if f.actor == "player" and f.week > since
            and f.kind in ("promise_broken", "flip_flop") and not f.extra.get("attacked")]


def options(state, data: dict) -> List[Option]:
    rv, tun = data["rival"], data["tuning"]
    out: List[Option] = []
    for gid in state.groups:
        recent = sum(1 for f in state.facts if f.kind == "rival_meeting" and f.group == gid and f.week >= state.week - 2)
        d = {gid: {"rival": float(rv["meeting_gain"]) * float(data["tuning"]["meeting_fatigue"]) ** recent}}
        out.append(Option("meet", _simulate(state, data, d), group=gid, deltas=d,
                          why="встреча даёт больше всего голосов здесь"))
    for sin in _sins(state, data):
        pr = next((p for p in state.promises if p.id == sin.extra.get("promise_id")), None)
        targets = list(state.groups) if sin.kind == "flip_flop" else (pr.groups if pr else [])
        d = {g: {"support": float(rv["attack_support"]), "trust": float(rv["attack_trust"])} for g in targets}
        if d:
            out.append(Option("attack", _simulate(state, data, d), proposal=sin.proposal, side=sin.side,
                              about=sin.id, deltas=d, why="кандидат подставился: " + sin.kind))
    stolen = state.rival_memory.setdefault("stolen", [])
    horizon = max(1, min(int(rv["plan_horizon"]), state.next_election_week - state.week))
    for pid, side in state.positions.items():
        if not side or state.rival_positions.get(pid) == side or pid in stolen:
            continue
        old = state.rival_positions.get(pid, 0)
        d = {}
        for gid in state.groups:
            st = float(data["proposals"][pid]["stance"][gid]) * float(data["groups"][gid]["salience"][pid]) / 100.0
            gain = float(tun["drift_k"]) * st * (side * STOLEN_CREDIT - old) * horizon
            d[gid] = {"rival": gain + float(rv["steal_cost_support"])}
        out.append(Option("steal", _simulate(state, data, d), proposal=pid, side=side, deltas=d,
                          why="перехват выгодной позиции кандидата"))
    behind = margin(state.groups, data) < 0
    if behind and state.week >= int(rv["dirty_after_week"]):
        best = max(state.groups, key=lambda g: (state.groups[g].support_player * data["groups"][g]["size"], g))
        d = {best: {"trust": float(rv["compromat_trust"])}}
        out.append(Option("compromat", _simulate(state, data, d), group=best, deltas=d,
                          why="проигрывает — бьёт по доверию в главной группе кандидата"))
        deficit = -margin(state.groups, data)
        out.append(Option("threat", float(rv["ruthlessness"]) * deficit * 0.4,
                          why="проигрывает — давит на кандидата лично"))
    return out


def plan(state, data: dict, rng: random.Random) -> Option:
    opts = options(state, data)
    # небольшой шум, чтобы при равенстве ходы не были механически предсказуемы
    return max(opts, key=lambda o: (o.value + rng.uniform(0, 1.0), o.kind, o.group, o.proposal))
