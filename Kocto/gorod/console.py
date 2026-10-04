"""Консольная игра «Город помнит». Запуск из папки Kocto:  python -m gorod.console"""
from __future__ import annotations

import sys
from pathlib import Path

from . import engine as E
from .parser import parse

SAVE_DIR = Path(__file__).resolve().parent.parent / "gorod_saves"
SLOT_RU = {"group": "группа", "proposal": "вопрос", "paper": "газета", "side": "позиция"}
HELP = """Пишите действие обычной фразой, например:
  встретиться с пенсионерами
  пообещать заморозку тарифов ЖКХ за 4 недели
  дать интервью «Голосу улицы» против расширения завода
  внести в совет сбор с торговли на ремонт дорог
Команды: статус · обещания · журнал · неделя (завершить неделю) · сохранить · загрузить · помощь · выход"""


def ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        raise SystemExit(0)


def choose(title: str, options):
    print(title)
    for i, (_, label) in enumerate(options, 1):
        print("  " + str(i) + ". " + label)
    while True:
        raw = ask("> номер (пусто — отмена): ")
        if not raw:
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        print("нужен номер от 1 до " + str(len(options)))


def fill_slot(data, card, slot) -> bool:
    if slot == "side":
        val = choose("Позиция?", [(1, "ЗА"), (-1, "ПРОТИВ")])
        if val is None:
            return False
        card.side = val
        return True
    table = {"group": "groups", "proposal": "proposals", "paper": "papers"}[slot]
    opts = [(k, v["forms"]["im"]) for k, v in data[table].items()]
    val = choose("Уточните: " + SLOT_RU[slot], opts)
    if val is None:
        return False
    setattr(card, slot, val)
    return True


def status(state, data) -> str:
    lines = ["Неделя " + str(state.week) + " · действий: " + str(state.actions_left) + " · деньги: "
             + str(state.money) + " · узнаваемость: " + str(round(state.awareness)) + " · выборы: неделя "
             + str(state.next_election_week) + " · роль: " + state.role]
    for gid, g in state.groups.items():
        lines.append("  " + data["groups"][gid]["forms"]["im"].ljust(16) + " вы " + str(round(g.support_player)).rjust(3)
                     + " · " + data["rival"]["forms"]["im"] + " " + str(round(g.support_rival)).rjust(3)
                     + " · доверие " + str(round(g.trust)).rjust(3))
    pos = [data["proposals"][p]["forms"]["im"] + ": " + data["sides"][str(v)]["name"]
           for p, v in state.positions.items() if v]
    lines.append("  Ваши позиции: " + ("; ".join(pos) if pos else "не заявлены"))
    return "\n".join(lines)


def promises(state, data) -> str:
    if not state.promises:
        return "Обещаний нет."
    ru = {"open": "в силе", "kept": "выполнено", "broken": "сорвано"}
    return "\n".join("  " + data["sides"][str(p.side)]["goal"].format_map(
        {"prop_rod": data["proposals"][p.proposal]["forms"]["rod"], "prop_vin": data["proposals"][p.proposal]["forms"]["vin"]})
        + " — до недели " + str(p.deadline_week) + " — " + ru[p.status] for p in state.promises)


def journal(state, n: int = 12) -> str:
    rows = state.facts[-n:]
    return "\n".join("  нед." + str(f.week) + " " + f.kind + " " + f.actor + " " + str(f.deltas) for f in rows) or "Журнал пуст."


def show_report(rep, data) -> None:
    print("\n=== Итоги недели " + str(rep["week"]) + " ===  доход +" + str(rep["income"]))
    for f in rep["world_facts"]:
        if f.kind.startswith("rival"):
            print("  Ход соперника: " + f.kind + " " + str(f.deltas))
        if f.kind == "promise_broken":
            print("  Сорвано обещание: " + data["proposals"][f.proposal]["forms"]["im"])
    for a in rep["articles"]:
        print("\n  " + a["paper_name"] + "\n  " + a["headline"] + "\n  " + a["lead"])
    if rep["election"]:
        e = rep["election"]
        print("\n=== ВЫБОРЫ: " + ("ПОБЕДА" if e["won"] else "ПОРАЖЕНИЕ") + " — " + str(e["player"]) + " : " + str(e["rival"]) + " ===")
        for r in e["rows"]:
            print("  " + data["groups"][r["group"]]["forms"]["im"].ljust(16) + " пришло " + str(r["voters"]).rjust(5)
                  + " · за вас " + str(round(r["share_player"] * 100)) + "%")
        print("  Игра продолжается: следующие выборы — неделя " + str(rep["week"] + data["meta"]["election_period_weeks"]))


def new_game(data):
    import skills  # Kocto/skills.py — общий распределитель очков навыков
    name = ask("Имя кандидата: ")
    gender = {"м": "m", "ж": "f"}.get(ask("Пол (м/ж): ").lower()[:1])
    while gender is None:
        gender = {"м": "m", "ж": "f"}.get(ask("Пол (м/ж): ").lower()[:1])
    while True:
        raw = ask("Распределите " + str(data["meta"]["skill_pool"]) + " очков: обаяние красноречие хитрость (например 30 40 20): ")
        try:
            return E.new_game(data, name, skills.parse(raw), gender)
        except (skills.SkillError, E.RuleError) as exc:
            print("Ошибка: " + str(exc))


def turn(state, data, text) -> None:
    res = parse(data, text)
    if res.card is None:
        print("Не понял: " + "; ".join(res.notes) + ". «помощь» — примеры.")
        return
    card = res.card
    for slot in E.missing_slots(data, card):
        if not fill_slot(data, card, slot):
            print("Отменено.")
            return
    for slot in E.missing_slots(data, card):  # side мог появиться после выбора вопроса
        if not fill_slot(data, card, slot):
            print("Отменено.")
            return
    pv = E.preview(state, data, card)
    print("Понято как: " + pv["summary"])
    for n in res.notes:
        print("  · " + n)
    for w in pv["warnings"]:
        print("  ! " + w)
    print("  шанс " + str(pv["chance"]) + "% · стоимость " + str(pv["cost"]))
    if ask("Выполнить? (Enter — да, н — нет): ").lower().startswith("н"):
        print("Отменено.")
        return
    try:
        out = E.perform(state, data, card)
    except E.RuleError as exc:
        print("Нельзя: " + str(exc))
        return
    ru = {"crit": "блестяще", "success": "успех", "fail": "неудача"}
    print("Бросок " + str(out["roll"]) + " + навык = " + str(out["total"]) + " против " + str(out["difficulty"])
          + " → " + ru[out["tier"]])
    for f in out["facts"]:
        print("  " + f.kind + ": " + ", ".join(k + " " + ("+" if v > 0 else "") + str(v) for k, v in f.deltas.items()))


def main() -> None:
    data = E.load_data()
    print(data["meta"]["title"] + "\n" + HELP)
    state = new_game(data)
    print(status(state, data))
    while True:
        cmd = ask("\n[" + str(state.week) + "] > ")
        low = cmd.lower()
        if not cmd:
            continue
        if low in ("выход", "exit"):
            return
        if low == "помощь":
            print(HELP)
        elif low == "статус":
            print(status(state, data))
        elif low == "обещания":
            print(promises(state, data))
        elif low == "журнал":
            print(journal(state))
        elif low in ("неделя", "конец"):
            show_report(E.end_week(state, data), data)
            print("\n" + status(state, data))
        elif low.startswith("сохранить"):
            SAVE_DIR.mkdir(exist_ok=True)
            path = SAVE_DIR / ((cmd[9:].strip() or "slot") + ".json")
            E.save_game(state, path)
            print("Сохранено: " + str(path))
        elif low.startswith("загрузить"):
            path = SAVE_DIR / ((cmd[9:].strip() or "slot") + ".json")
            try:
                state = E.load_game(path)
                print(status(state, data))
            except E.DataError as exc:
                print("Ошибка: " + str(exc))
        else:
            if state.actions_left <= 0:
                print("Действия на неделю закончились — введите «неделя».")
                continue
            turn(state, data, cmd)


if __name__ == "__main__":
    sys.exit(main())
