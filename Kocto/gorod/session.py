"""Сценарий хода без интерфейса: фраза → карточка → уточнения → подтверждение → итог.

Его используют и окно (ui_tk.py), и тесты. Окно только рисует то, что возвращает Session.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from . import engine as E
from .parser import Parse, parse

SLOT_RU = {"group": "группа", "proposal": "вопрос", "paper": "газета", "side": "позиция"}
TIER_RU = {"crit": "блестяще", "success": "успех", "fail": "неудача"}
KIND_RU = {
    "meeting_ok": "встреча прошла хорошо", "meeting_fail": "встреча не задалась", "statement": "заявление",
    "statement_weak": "повтор позиции", "flip_flop": "смена позиции", "promise": "обещание",
    "promise_kept": "обещание выполнено", "promise_broken": "обещание сорвано", "initiative_ok": "решение совета",
    "initiative_fail": "провал в совете", "interview_ok": "интервью", "interview_gaffe": "оговорка в интервью",
    "rival_meeting": "соперник встретился с группой", "rival_attack": "соперник напомнил о вашем промахе",
    "rival_statement": "соперник перехватил позицию", "rival_compromat": "компромат", "rival_threat": "давление на вас",
    "security": "охрана усилена", "security_lost": "охрана ослабла", "publicize": "угрозы преданы огласке",
    "publicize_panic": "заявление об угрозах не убедило", "threat_warning": "предупреждение об угрозе",
    "attack_failed": "покушение сорвано", "attack_injury": "ранение", "death": "гибель", "election": "выборы"}


def threat_label(v: float) -> str:
    return "низкая" if v < 30 else ("заметная" if v < 60 else "высокая")


class Session:
    def __init__(self, data: Optional[dict] = None):
        self.data = data or E.load_data()
        self.state: Optional[E.State] = None
        self.pending: Optional[E.Card] = None
        self.parsed: Optional[Parse] = None

    # ---------- кампания ----------
    def new(self, name: str, gender: str, skills: dict, seed: Optional[int] = None) -> None:
        self.state = E.new_game(self.data, name, skills, gender, seed=seed)
        self.cancel()

    def save(self, path: Path) -> None:
        E.save_game(self._st(), path)

    def load(self, path: Path) -> None:
        self.state = E.load_game(path)
        self.cancel()

    def _st(self) -> E.State:
        if self.state is None:
            raise E.RuleError("кампания не начата")
        return self.state

    @property
    def over(self) -> bool:
        return bool(self.state and self.state.dead)

    # ---------- ход ----------
    def understand(self, text: str) -> dict:
        self.parsed = parse(self.data, text)
        self.pending = self.parsed.card
        return self.view()

    def set_slot(self, slot: str, value) -> dict:
        if self.pending is None:
            raise E.RuleError("нет карточки")
        if slot == "side":
            value = int(value)
            if value not in (-1, 1):
                raise E.RuleError("позиция: 1 или -1")
        elif value not in self.data[{"group": "groups", "proposal": "proposals", "paper": "papers"}[slot]]:
            raise E.RuleError("нет такого значения: " + str(value))
        setattr(self.pending, slot, value)
        if slot == "proposal" and self.pending.side == 0:
            self.pending.side = 1
        return self.view()

    def options(self, slot: str) -> List[tuple]:
        if slot == "side":
            return [(1, "ЗА"), (-1, "ПРОТИВ")]
        table = {"group": "groups", "proposal": "proposals", "paper": "papers"}[slot]
        return [(k, v["forms"]["im"]) for k, v in self.data[table].items()]

    def view(self) -> dict:
        if self.pending is None:
            notes = self.parsed.notes if self.parsed else []
            return {"ok": False, "summary": "Не понял фразу.", "notes": notes, "missing": [], "warnings": []}
        pv = E.preview(self._st(), self.data, self.pending)
        return {"ok": True, "summary": pv["summary"], "notes": list(self.parsed.notes) if self.parsed else [],
                "warnings": pv["warnings"], "missing": pv["missing"], "chance": pv["chance"], "cost": pv["cost"],
                "source": self.parsed.source if self.parsed else "", "ready": not pv["missing"]}

    def cancel(self) -> None:
        self.pending, self.parsed = None, None

    def confirm(self) -> List[str]:
        if self.pending is None:
            raise E.RuleError("нет карточки")
        out = E.perform(self._st(), self.data, self.pending)
        self.cancel()
        lines = ["Бросок " + str(out["roll"]) + " + навык = " + str(out["total"]) + " против "
                 + str(out["difficulty"]) + " → " + TIER_RU[out["tier"]]]
        lines += ["  " + fact_line(self.data, f) for f in out["facts"]]
        return lines

    def end_week(self) -> dict:
        self.cancel()
        rep = E.end_week(self._st(), self.data)
        lines = ["— Итоги недели " + str(rep["week"]) + " · доход +" + str(rep["income"])]
        lines += ["  " + fact_line(self.data, f) for f in rep["world_facts"]]
        e = rep["election"]
        if e:
            lines.append("ВЫБОРЫ: " + ("ПОБЕДА" if e["won"] else "ПОРАЖЕНИЕ") + " " + str(e["player"]) + " : " + str(e["rival"]))
            for r in e["rows"]:
                lines.append("  " + self.data["groups"][r["group"]]["forms"]["im"] + ": пришло " + str(r["voters"])
                             + ", за вас " + str(round(r["share_player"] * 100)) + "%")
        if rep["dead"]:
            lines.append("ИГРА ОКОНЧЕНА: кандидат погиб на неделе " + str(rep["week"]) + ".")
        rep["lines"] = lines
        return rep

    # ---------- обзор ----------
    def status(self) -> dict:
        s, d = self._st(), self.data
        forecast = E.election(s, d, None)
        return {
            "week": s.week, "actions_left": s.actions_left, "money": s.money, "awareness": round(s.awareness),
            "role": s.role, "next_election": s.next_election_week, "dead": s.dead,
            "threat": round(s.threat), "threat_label": threat_label(s.threat), "security": s.security,
            "injured": s.week <= s.injured_until,
            "forecast": {"player": forecast["player"], "rival": forecast["rival"]},
            "groups": [{"id": gid, "name": d["groups"][gid]["forms"]["im"], "player": round(g.support_player),
                        "rival": round(g.support_rival), "trust": round(g.trust)} for gid, g in s.groups.items()],
            "positions": [(d["proposals"][p]["forms"]["im"], d["sides"][str(v)]["name"]) for p, v in s.positions.items() if v],
            "rival_positions": [(d["proposals"][p]["forms"]["im"], d["sides"][str(v)]["name"])
                                for p, v in s.rival_positions.items() if v],
            "promises": [promise_line(d, p) for p in s.promises]}


def promise_line(data: dict, p) -> str:
    forms = data["proposals"][p.proposal]["forms"]
    goal = data["sides"][str(p.side)]["goal"].format_map({"prop_rod": forms["rod"], "prop_vin": forms["vin"]})
    ru = {"open": "в силе", "kept": "выполнено", "broken": "сорвано"}
    return goal + " — до недели " + str(p.deadline_week) + " — " + ru[p.status]


def fact_line(data: dict, f) -> str:
    parts = [KIND_RU.get(f.kind, f.kind)]
    for key, v in f.deltas.items():
        gid, kind = key.split(".")
        name = data["groups"][gid]["forms"]["im"]
        what = {"support": "поддержка", "trust": "доверие", "rival": data["rival"]["forms"]["im"]}[kind]
        parts.append(name + " " + what + " " + ("+" if v > 0 else "") + str(round(v, 1)))
    if f.extra.get("why"):
        parts.append("(" + str(f.extra["why"]) + ")")
    return " · ".join(parts)
