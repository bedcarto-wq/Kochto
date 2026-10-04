"""Консольная игра «Город помнит». Запуск из папки Kocto:  python -m gorod.console"""
from __future__ import annotations

import sys
from pathlib import Path

from . import engine as E
from .session import SLOT_RU, Session

SAVE_DIR = Path(__file__).resolve().parent.parent / "gorod_saves"
HELP = """Пишите действие обычной фразой, например:
  встретиться с пенсионерами
  пообещать заморозку тарифов ЖКХ за 4 недели
  дать интервью «Голосу улицы» против расширения завода
  внести в совет сбор с торговли на ремонт дорог
  нанять охрану · заявить об угрозах
Команды: статус · обещания · неделя (завершить неделю) · сохранить [имя] · загрузить [имя] · помощь · выход"""


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


def print_status(ses: Session) -> None:
    st = ses.status()
    print("Неделя " + str(st["week"]) + " · действий: " + str(st["actions_left"]) + " · деньги: " + str(st["money"])
          + " · узнаваемость: " + str(st["awareness"]) + " · выборы: неделя " + str(st["next_election"])
          + " · роль: " + st["role"] + (" · РАНЕН" if st["injured"] else ""))
    for g in st["groups"]:
        print("  " + g["name"].ljust(16) + " вы " + str(g["player"]).rjust(3) + " · соперник "
              + str(g["rival"]).rjust(3) + " · доверие " + str(g["trust"]).rjust(3))
    f = st["forecast"]
    print("  Прогноз: вы " + str(f["player"]) + " · соперник " + str(f["rival"]))
    print("  Угроза: " + st["threat_label"] + " (" + str(st["threat"]) + ") · охрана " + str(st["security"]))
    print("  Ваши позиции: " + ("; ".join(p + ": " + s for p, s in st["positions"]) or "не заявлены"))


def new_game(ses: Session) -> None:
    import skills  # Kocto/skills.py — общий распределитель очков навыков
    name = ask("Имя кандидата: ")
    gender = None
    while gender is None:
        gender = {"м": "m", "ж": "f"}.get(ask("Пол (м/ж): ").lower()[:1])
    while True:
        raw = ask("Распределите " + str(ses.data["meta"]["skill_pool"])
                  + " очков: обаяние красноречие хитрость (например 30 40 20): ")
        try:
            ses.new(name, gender, skills.parse(raw))
            return
        except (skills.SkillError, E.RuleError) as exc:
            print("Ошибка: " + str(exc))


def turn(ses: Session, text: str) -> None:
    view = ses.understand(text)
    if not view["ok"]:
        print("Не понял: " + "; ".join(view["notes"]) + ". «помощь» — примеры.")
        return
    while view["missing"]:
        slot = view["missing"][0]
        val = choose("Уточните: " + SLOT_RU[slot], ses.options(slot))
        if val is None:
            ses.cancel()
            print("Отменено.")
            return
        view = ses.set_slot(slot, val)
    print("Понято как: " + view["summary"])
    for n in view["notes"]:
        print("  · " + n)
    for w in view["warnings"]:
        print("  ! " + w)
    print("  шанс " + str(view["chance"]) + "% · стоимость " + str(view["cost"]))
    if ask("Выполнить? (Enter — да, н — нет): ").lower().startswith("н"):
        ses.cancel()
        print("Отменено.")
        return
    try:
        for line in ses.confirm():
            print(line)
    except E.RuleError as exc:
        print("Нельзя: " + str(exc))


def main() -> None:
    ses = Session()
    print(ses.data["meta"]["title"] + "\n" + HELP)
    new_game(ses)
    print_status(ses)
    while True:
        cmd = ask("\n[" + str(ses.state.week) + "] > ")
        low = cmd.lower()
        if not cmd:
            continue
        if low in ("выход", "exit"):
            return
        if low == "помощь":
            print(HELP)
        elif low == "статус":
            print_status(ses)
        elif low == "обещания":
            print("\n".join("  " + p for p in ses.status()["promises"]) or "Обещаний нет.")
        elif low in ("неделя", "конец"):
            if ses.over:
                print("Игра окончена.")
                continue
            rep = ses.end_week()
            print("\n".join(rep["lines"]))
            for a in rep["articles"]:
                print("\n  " + a["paper_name"] + "\n  " + a["headline"] + "\n  " + a["lead"])
            if rep["dead"]:
                print("\nИГРА ОКОНЧЕНА.")
                continue
            print()
            print_status(ses)
        elif low.startswith("сохранить"):
            SAVE_DIR.mkdir(exist_ok=True)
            path = SAVE_DIR / ((cmd[9:].strip() or "slot") + ".json")
            ses.save(path)
            print("Сохранено: " + str(path))
        elif low.startswith("загрузить"):
            try:
                ses.load(SAVE_DIR / ((cmd[9:].strip() or "slot") + ".json"))
                print_status(ses)
            except E.DataError as exc:
                print("Ошибка: " + str(exc))
        else:
            if ses.over:
                print("Игра окончена.")
            elif ses.state.actions_left <= 0:
                print("Действия на неделю закончились — введите «неделя».")
            else:
                turn(ses, cmd)


if __name__ == "__main__":
    sys.exit(main())
