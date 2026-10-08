"""Сценарий хода без интерфейса: фраза → карточка → уточнения → подтверждение → итог.

Его используют и окно (ui_tk.py), и тесты. Окно только рисует то, что возвращает Session.
"""
from __future__ import annotations

import copy
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

from . import engine as E
from .improver import improve
from .parser import Parse, parse
from . import intent as I

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
    "negotiation_offer": "председатель предложил условия", "negotiation_accept": "условия приняты", "negotiation_reject": "председатель отказал", "deal_kept": "договор выполнен", "deal_broken": "договор нарушен",
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
        self.intent = None
        self.selected_step = 0

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
        self.cancel()
        self.text = text
        self.intent = I.analyze(self.data, text, self._st())
        self.selected_step = 0
        self._select_pending()
        return self.view()

    def _select_pending(self):
        if self.intent and self.intent.steps:
            step = self.intent.steps[self.selected_step]
            self.pending = step.card
            self.parsed = Parse(step.card, source=step.source, confidence=step.confidence, notes=step.notes)
        else:
            self.pending = None
            self.parsed = Parse(None, notes=list(self.intent.blocked) if self.intent else [])

    def select_step(self, index):
        if self.intent is None or type(index) is not int or not 0 <= index < len(self.intent.steps):
            raise E.RuleError("нет такого шага")
        self.selected_step = index
        self._select_pending()
        return self.view()

    def suggest(self, text: str) -> List[dict]:
        """Режим улучшателя: варианты формулировок; игрок выбирает свой текст или один из них."""
        graph = I.analyze(self.data, text, self._st())
        if graph.blocked or any(step.blocked or step.condition for step in graph.steps) or len(graph.steps)>1:
            return []  # never erase conditions/negations while polishing wording
        return improve(self.data, text, self._st().learned)

    def manual(self, action: str) -> dict:
        """Режим карточки: игрок сам выбирает действие и слоты, текст не разбирается."""
        if action not in self.data["actions"]:
            raise E.RuleError("нет такого действия: " + str(action))
        self.cancel()
        self.parsed, self.text = None, ""
        self.pending = E.Card(action=action)
        if action == 'accept_deal':
            offer = E.open_offer(self._st())
            if offer:
                self.pending.proposal, self.pending.side = offer['proposal'], offer['side']
        if action in ("promise", "negotiate"):
            self.pending.deadline = int(self.data["actions"][action]["default_deadline"])
        return self.view()

    def set_action(self, action: str) -> dict:
        """Игрок исправляет понятое действие. Исправление запоминается для ИИ этой кампании."""
        if self.pending is None or action not in self.data["actions"]:
            raise E.RuleError("нет карточки или такого действия")
        self.pending.action = action
        if self.intent:
            step = self.intent.steps[self.selected_step]
            relevant = set(self.data['actions'][action]['requires'])
            if action == 'interview': relevant.update(('group', 'proposal', 'paper'))
            if action == 'accept_deal': relevant.add('proposal')
            for field in ('group', 'proposal', 'paper'):
                if field not in relevant: step.ambiguities.pop(field, None)
            step.ambiguities.pop('action', None)
            if action not in ('statement','promise','initiative','negotiate','interview'):
                step.ambiguities.pop('side', None)
            step.source = 'исправлено игроком'
            if not step.blocked:
                step.speech_act = {'promise':'commitment','negotiate':'offer','accept_deal':'acceptance'}.get(action,'instruction')
            step.evidence.append({'field':'action','source':'игрок','value':action})
        if action in ("promise", "negotiate") and not self.pending.deadline:
            self.pending.deadline = int(self.data["actions"][action]["default_deadline"])
        if self.parsed is not None:  # заметки о старой догадке больше не верны
            stale = ("предполагаю", "понято по смыслу", "не учитывается", "несколько действий", "уже уточняли")
            self.parsed.notes = [n for n in self.parsed.notes if not any(x in n for x in stale)]
            self.parsed.notes.append("действие исправлено вами — игра это запомнит")
            if self.intent:
                self.intent.steps[self.selected_step].notes = list(self.parsed.notes)
        return self.view()

    def set_deadline(self, weeks: int) -> dict:
        if self.pending is None or self.pending.action not in ("promise", "negotiate"):
            raise E.RuleError("срок бывает у обещания или переговоров")
        self.pending.deadline = int(weeks)
        if self.intent:
            self.intent.steps[self.selected_step].evidence.append({'field':'deadline','source':'игрок','value':int(weeks)})
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
        if slot == 'proposal' and self.pending.action == 'accept_deal':
            offer = E.open_offer(self._st(), value)
            if offer:
                self.pending.side = offer['side']
        if self.intent:
            self.intent.steps[self.selected_step].ambiguities.pop(slot, None)
            self.intent.steps[self.selected_step].evidence.append({'field':slot,'source':'игрок','value':value})
        if slot == "proposal" and self.pending.side == 0 and self.intent is None:
            self.pending.side = 1
        return self.view()

    def options(self, slot: str) -> List[tuple]:
        if slot == "side":
            return [(1, "ЗА"), (-1, "ПРОТИВ")]
        table = {"group": "groups", "proposal": "proposals", "paper": "papers"}[slot]
        return [(k, v["forms"]["im"]) for k, v in self.data[table].items()]

    def view(self) -> dict:
        if self.pending is None:
            notes = list(self.parsed.notes) if self.parsed else []
            if self.intent:
                notes += self.intent.blocked
                notes += [x for step in self.intent.steps for x in step.blocked]
            return {"ok": False, "summary": "Не найдено безопасное исполнимое намерение.", "notes": list(dict.fromkeys(notes)),
                    "missing": [], "warnings": [], "ready": False}
        pv = E.preview(self._st(), self.data, self.pending)
        missing = list(pv['missing'])
        warnings = list(pv['warnings'])
        notes = list(self.parsed.notes) if self.parsed else []
        ready = not missing
        source = self.parsed.source if self.parsed else 'карточка'
        summary = pv['summary']
        steps = []
        if self.intent:
            current = self.intent.steps[self.selected_step]
            missing += [k for k in current.ambiguities if k != 'action' and k not in missing]
            source = current.source
            notes = list(current.notes) + current.blocked + self.intent.blocked
            for n, step in enumerate(self.intent.steps, 1):
                desc = E.describe_card(self.data, step.card) if step.card else 'не распознано'
                steps.append(str(n) + '. ' + desc)
            summary = '\n'.join(steps)
            try:
                I.compile_intent(self._st(), self.data, self.intent)
            except E.RuleError as exc:
                warnings += str(exc).split('\n')
                ready = False
            else:
                ready = True
            if len(steps)>1:
                notes.append('План расходует '+str(len(steps))+' действий. Уточнения относятся к выбранному шагу.')
            if current.condition:
                notes.append('Условие: '+current.condition.text)
        return {"ok": True, "summary": summary, "notes": notes, "warnings": list(dict.fromkeys(warnings)),
                "missing": missing, "chance": pv["chance"], "cost": sum(self.data['actions'][x.card.action]['cost'] for x in self.intent.steps if x.card) if self.intent else pv['cost'],
                "source": source, "ready": ready, "action": self.pending.action, "deadline": self.pending.deadline,
                "steps": steps, "selected_step": self.selected_step,
                "semantic": self.intent.record() if self.intent else None}

    def cancel(self) -> None:
        self.pending, self.parsed, self.text = None, None, ""
        self.intent = None
        self.selected_step = 0

    def confirm(self) -> List[str]:
        if self.pending is None:
            raise E.RuleError("нет карточки")
        if self.intent:
            cards, conditions = I.compile_intent(self._st(), self.data, self.intent)
        else:
            I.validate_card(self.data, self.pending)
            cards, conditions = [copy.deepcopy(self.pending)], [None]
        # Commit the whole plan only if all operations are legal. Failed dice are
        # normal results, not validation errors; their costs remain paid.
        original = self._st()
        scratch = copy.deepcopy(original)
        lines = []
        for index, (card, condition) in enumerate(zip(cards, conditions), 1):
            if not I.condition_ok(scratch, condition):
                raise E.RuleError('Условие шага '+str(index)+' больше не выполнено')
            out = E.perform(scratch, self.data, card)
            if len(cards)>1:
                lines.append('Шаг '+str(index)+'/'+str(len(cards))+': '+E.describe_card(self.data, card))
            lines += result_lines(self.data, card, out)
            text = card.text if self.intent else self.text
            if text:
                E.learn(scratch, self.data, text, card.action)
        if self.intent:
            I.remember(scratch, self.data, self.intent)
        original.__dict__.clear()
        original.__dict__.update(scratch.__dict__)
        self.cancel()
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
            "promises": [promise_line(d, p) for p in s.promises] + [deal_line(d, x) for x in s.negotiations if x['status'] in ('offered','accepted')],
            "speaker_loyalty": s.npc_loyalty['speaker']}


def result_lines(data, card, out):
    lines = (["Предложение председателя принято (без броска)."] if card.action == 'accept_deal' else
             ["Бросок " + str(out['roll']) + " + навык = " + str(out['total']) + " против " + str(out['difficulty']) + " → " + TIER_RU[out['tier']]])
    return lines + ["  " + fact_line(data, f) for f in out['facts']]


def deal_line(data, deal):
    name = data['proposals'][deal['proposal']]['forms']['im']
    side = data['sides'][str(deal['side'])]['name']
    if deal['status'] == 'offered':
        return 'Председатель предлагает: '+name+' — '+side+'; принять до недели '+str(deal['expires_week'])+'; выполнить за '+str(deal['term'])+' нед.'
    return 'Договор с советом: '+name+' — '+side+'; решение до недели '+str(deal['deadline_week'])


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
    if f.extra.get("reason"):
        parts.append(str(f.extra["reason"]))
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
    winner = "ничья (новый мэр не назначен)" if e["player"] == e["rival"] else (state.player_name if e["won"] else rival)
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
