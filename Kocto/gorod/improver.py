"""Улучшатель текста: по фразе игрока предлагает 1–3 чётких формулировки.

Каждая формулировка собирается из данных (data['improver']) и при повторном разборе
даёт ровно ту же карточку — игрок видит, как игра его поймёт, и выбирает:
свой текст или улучшенный.
"""
from __future__ import annotations

import copy
from typing import List

from .engine import Card, describe_card
from .parser import model, parse, tokens

ALT_MIN = 0.15


def phrase(data: dict, card: Card) -> str:
    imp = data["improver"]
    s = {}
    miss = imp["missing"]
    if card.group:
        for case, v in data["groups"][card.group]["forms"].items():
            s["group_" + case] = v
    else:
        for case in ("im", "rod", "dat", "vin", "tv", "pr"):
            s["group_" + case] = miss["group"]
    if card.paper:
        for case, v in data["papers"][card.paper]["forms"].items():
            s["paper_" + case] = v
    else:
        for case in ("im", "dat", "pr"):
            s["paper_" + case] = miss["paper"]
    if card.proposal:
        forms = data["proposals"][card.proposal]["forms"]
        side = data["sides"][str(card.side if card.side in (-1, 1) else 1)]
        fm = {"prop_" + k: v for k, v in forms.items()}
        s["side_pos"] = side["pos"].format_map(fm)
        s["side_goal"] = side["goal"].format_map(fm)
    else:
        s["side_pos"] = s["side_goal"] = miss["proposal"]
    s["deadline"] = str(card.deadline or data["actions"]["promise"]["default_deadline"])
    key = "interview_topic" if card.action == "interview" and card.proposal else card.action
    return imp[key].format_map(s)


def improve(data: dict, text: str, learned=None) -> List[dict]:
    res = parse(data, text, learned)
    if res.card is None:
        return []
    cards = [res.card]
    m = model(data, learned)
    probs = m.predict(tokens(text)) if m is not None else None
    alts = list(res.alternatives)
    if probs:
        alts += [a for a, p in sorted(probs.items(), key=lambda kv: -kv[1]) if p >= ALT_MIN and a not in alts]
    for a in alts:
        if a != res.card.action and len(cards) < 3:
            c = copy.deepcopy(res.card)
            c.action = a
            cards.append(c)
    out = []
    for c in cards:
        out.append({"text": phrase(data, c), "summary": describe_card(data, c), "action": c.action,
                    "complete": not any(m in phrase(data, c) for m in data["improver"]["missing"].values())})
    return out
