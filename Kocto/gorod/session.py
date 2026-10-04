"""Сценарий хода без интерфейса: фраза → карточка → уточнения → подтверждение → итог.

Его используют и окно (ui_tk.py), и тесты. Окно только рисует то, что возвращает Session.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from . import engine as E
from .improver import improve
from .parser import Parse, parse

MODES = {"text": "Свободный текст", "improver": "Текст + улучшатель", "card": "Карточка вручную"}

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
        self.text = ""
        self.mode = "text"

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise E.RuleError("режим: " + ", ".join(MODES))
        self.mode = mode
        self.cancel()

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
        self.text = text
        self.parsed = parse(self.data, text, self._st().learned)
        self.pending = self.parsed.card
        return self.view()

    def suggest(self, text: str) -> List[dict]:
        """Режим улучшателя: варианты формулировок; игрок выбирает свой текст или один из них."""
        return improve(self.data, text, self._st().learned)

    def manual(self, action: str) -> dict:
        """Режим карточки: игрок сам выбирает действие и слоты, текст не разбирается."""
        if action not in self.data["actions"]:
            raise E.RuleError("нет такого действия: " + str(action))
        self.parsed, self.text = None, ""
        self.pending = E.Card(action=action)
        if action == "promise":
            self.pending.deadline = int(self.data["actions"]["promise"]["default_deadline"])
        return self.view()

    def set_action(self, action: str) -> dict:
        """Игрок исправляет понятое действие. Исправление запоминается для ИИ этой кампании."""
        if self.pending is None or action not in self.data["actions"]:
            raise E.RuleError("нет карточки или такого действия")
        self.pending.action = action
        if action == "promise" and not self.pending.deadline:
            self.pending.deadline = int(self.data["actions"]["promise"]["default_deadline"])
        if self.parsed is not None:  # заметки о старой догадке больше не верны
            stale = ("предполагаю", "понято по смыслу", "не учитывается", "несколько действий", "уже уточняли")
            self.parsed.notes = [n for n in self.parsed.notes if not any(x in n for x in stale)]
            self.parsed.notes.append("действие исправлено вами — игра это запомнит")
        return self.view()

    def set_deadline(self, weeks: int) -> dict:
        if self.pending is None or self.pending.action != "promise":
            raise E.RuleError("срок бывает только у обещания")
        self.pending.deadline = int(weeks)
        return self.view()

    def actions(self) -> List[tuple]:
        return [(k, v["name"]) for k, v in self.data["actions"].items()]

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
            return {"ok": False, "summary": "Не понял фразу.", "notes": notes, "missing": [], "warnings": [],
                    "ready": False}
        pv = E.preview(self._st(), self.data, self.pending)
        return {"ok": True, "summary": pv["summary"], "notes": list(self.parsed.notes) if self.parsed else [],
                "warnings": pv["warnings"], "missing": pv["missing"], "chance": pv["chance"], "cost": pv["cost"],
                "source": self.parsed.source if self.parsed else "карточка", "ready": not pv["missing"],
                "action": self.pending.action, "deadline": self.pending.deadline}

    def cancel(self) -> None:
        self.pending, self.parsed, self.text = None, None, ""

    def confirm(self) -> List[str]:
        if self.pending is None:
            raise E.RuleError("нет карточки")
        card, text = self.pending, self.text
        out = E.perform(self._st(), self.data, card)
        if text:
            E.learn(self._st(), self.data, text, card.action)
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
        if e:
            rep["chart"] = election_chart(self.data, self._st(), e)
        if rep["dead"]:
            lines.append("ИГРА ОКОНЧЕНА: кандидат погиб на неделе " + str(rep["week"]) + ".")
        rep["lines"] = lines
        return rep

    def forecast_chart(self) -> dict:
        return election_chart(self.data, self._st(), E.election(self._st(), self.data, None), forecast=True)

    def export_learned(self, path: Path) -> int:
        """Выгрузить выученные фразы кампании для ручной проверки и пополнения корпуса."""
        import json
        rows = [{"text": t, "action": a, "split": "train", "source": "player"} for t, a in self._st().learned]
        Path(path).write_text(json.dumps({"phrases": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
        return len(rows)

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


def election_chart(data: dict, state, e: dict, forecast: bool = False) -> dict:
    """Данные для столбчатой диаграммы: мэр, группы, совет. Окно и консоль только рисуют."""
    total = (e["player"] + e["rival"]) or 1
    rival = data["rival"]["forms"]["im"]
    mayor = [(state.player_name, round(100 * e["player"] / total, 1)), (rival, round(100 * e["rival"] / total, 1))]
    groups = [(data["groups"][r["group"]]["forms"]["im"], round(100 * r["share_player"], 1),
               round(100 * (1 - r["share_player"]), 1)) for r in e["rows"]]
    co = e["council"]
    lists = data["council"]["lists"]
    name = {lid: (lst["name"] if lst["vote"] != "player" else lst["name"] + " (" + state.player_name + ")")
            for lid, lst in lists.items()}
    council = [(name[lid], round(100 * co["share"][lid], 1), co["seats"][lid]) for lid in lists]
    winner = state.player_name if e["won"] else rival
    seats_txt = ", ".join(n + " — " + str(k) for n, _, k in council)
    caption = (("Прогноз. " if forecast else "") + "Мэр: " + winner + ". Мандаты совета ("
               + str(data["council"]["seats"]) + "): " + seats_txt + ". Порог "
               + str(round(100 * data["council"]["threshold"])) + "%.")
    return {"title": "Прогноз выборов" if forecast else "Итоги выборов", "mayor": mayor, "groups": groups,
            "council": council, "caption": caption, "you": state.player_name, "rival": rival}


def ascii_chart(chart: dict, width: int = 30) -> List[str]:
    def bar(p):
        n = int(round(width * p / 100))
        return "█" * n + "·" * (width - n)
    out = ["=== " + chart["title"] + " ===", "Мэр:"]
    for n, p in chart["mayor"]:
        out.append("  " + n[:22].ljust(22) + " " + bar(p) + " " + str(p) + "%")
    out.append("По группам (за вас):")
    for n, p, _ in chart["groups"]:
        out.append("  " + n[:22].ljust(22) + " " + bar(p) + " " + str(p) + "%")
    out.append("Совет:")
    for n, p, k in chart["council"]:
        out.append("  " + n[:22].ljust(22) + " " + bar(p) + " " + str(p) + "% · мест " + str(k))
    out.append(chart["caption"])
    return out
