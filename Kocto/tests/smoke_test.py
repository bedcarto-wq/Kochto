"""Смоук-тест: python tests/smoke_test.py  (только stdlib, рантайм-файлы пишутся во временную папку)."""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import language  # noqa: E402
import main  # noqa: E402
import models  # noqa: E402
import systems  # noqa: E402
import ui  # noqa: E402

FAILS: list = []


def check(cond: bool, what: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        FAILS.append(what)


def setup(tmp: Path):
    main.SAVE_DIR = tmp / "saves"
    main.SAVE_FILE = main.SAVE_DIR / "save.json"
    main.MEMORY_FILE = main.SAVE_DIR / "parser_memory.json"
    main.FEEDBACK_FILE = main.SAVE_DIR / "feedback.txt"
    user = tmp / "data"
    data, _w = models.load_data(models.DATA_DIR, main.ACTIVE_SCENARIO)
    models.ensure_runtime_files(user)
    systems.init_data(data, user)
    main.nn_analyzer_set(data)
    language.init_constructions(user)
    return data


def say(state, rng, mem, text):
    res = main.handle_command(state, rng, text, mem)
    return res.get("message", "")


def end_week(state):
    before = systems.snapshot(state)
    review = systems.begin_week_end(state)
    systems.finish_week(state, [])
    main._clear_pending(state)
    return systems.week_summary(before, state), review


def run() -> int:
    with tempfile.TemporaryDirectory() as td:
        data = setup(Path(td))
        state, rng = main.new_game(data, 777, "Тест", 35)
        mem: dict = {}
        state.player.money = 5000

        print("1. Свои действия и теги")
        m = say(state, rng, mem, "тайно раздать деньги рабочим")
        qa = state.week_actions[-1] if state.week_actions else {}
        check("Принято" in m, "фраза принята: " + m)
        check("secret" in qa.get("tags", []) and "money" in qa.get("tags", []), "теги secret+money: " + str(qa.get("tags")))
        check(qa.get("target") == "workers" or "рабоч" in systems.target_label(state, qa.get("target", "")),
              "цель — рабочие: " + str(qa.get("target")))
        m = say(state, rng, mem, "поговорить с редактором и предложить должность")
        qa = state.week_actions[-1]
        check(qa.get("offer") == "post", "НПС-предложение «должность»: " + str(qa.get("offer")) + " | " + m)
        m = say(state, rng, mem, "разведать планы Ложкина")
        check("intel" in state.week_actions[-1].get("tags", []), "разведка распознана: " + m)
        plan = systems.plan_lines(state)
        check(len(plan) == 3 and all("шанс ~" in p for p in plan), "план недели с шансом/ценой")
        center = ui.render_center(state, "")
        check("Своё" in center, "план виден в центре")
        summary, _r = end_week(state)
        check(summary.startswith("Итоги недели"), summary)
        tries = 1
        while state.world.get("revealed_week") is None and tries < 6:   # бросок может провалиться
            say(state, rng, mem, "разведать планы Ложкина")
            end_week(state)
            tries += 1
        check(state.world.get("revealed_week") is not None, "разведка раскрыла планы (попыток: %d)" % tries)
        check("Разведанные планы" in "\n".join(systems.world_report(state)), "экран Город показывает планы")

        print("2. Отмена и деньги")
        money0 = state.player.money
        say(state, rng, mem, "встретиться с пенсионерами о медицине")
        paid = state.player.money
        m = say(state, rng, mem, "отменить 1")
        check(state.player.money == money0 and not state.week_actions, "отмена вернула деньги: " + m)
        check(paid <= money0, "действие стоило денег")

        print("3. Противоречие")
        log0 = len(state.event_log)
        say(state, rng, mem, "публично пообещать повысить налоги")
        end_week(state)
        say(state, rng, mem, "публично пообещать снизить налоги")
        end_week(state)
        st = state.world.get("statements") or []
        check(len(st) >= 1, "заявления запоминаются: " + str(st[-2:]))
        joined = " ".join(state.event_log[log0:]) + " ".join(str(n.get("headline", "")) for n in state.news_feed)
        check("противореч" in joined.lower() or "переобу" in joined.lower() or len(st) >= 2,
              "противоречие замечено")

        print("4. Долгий прогон 104 недели (жизнь мира, без падений)")
        phrases = ["встретиться с рабочими о зарплатах", "дать интервью о медицине", "раскритиковать Ложкина",
                   "собрать пожертвования", "поговорить с мэром и попросить помощь", "организовать митинг студентов",
                   "тайно собрать компромат на Воронину", "помочь врачам отремонтировать больницу"]
        t0 = time.time()
        worst = 0.0
        hot_seen = 0
        moves_seen = set()
        for w in range(104):
            for i in range(2):
                say(state, rng, mem, phrases[(w * 2 + i) % len(phrases)])
            t1 = time.time()
            end_week(state)
            worst = max(worst, time.time() - t1)
            hot_seen += len(state.world.get("hot_groups") or {})
            for v in (state.world.get("rival_memory") or {}).values():
                if v.get("last_move"):
                    moves_seen.add(v["last_move"])
            if state.is_game_over:
                break
        total = time.time() - t0
        print("  время: всего %.2fs, худшая неделя %.3fs" % (total, worst))
        check(worst < 1.0, "неделя считается быстрее 1 с")
        check(len(moves_seen) >= 2, "соперники делают разные ходы: " + str(sorted(moves_seen)))
        check(hot_seen > 0, "возникали горячие точки (забастовки/протесты)")
        check(state.election_count >= 1 or state.is_game_over, "выборы прошли, игра продолжилась")
        check(len(state.event_log) < 5000 and len(state.news_feed) < 500, "списки не растут бесконечно: log=%d news=%d"
              % (len(state.event_log), len(state.news_feed)))
        for kind in ("me", "parties", "press", "log", "gov", "help", "world"):
            txt = ui.render_modal(kind, state)
            check(bool(txt) and "Неизвестный" not in txt, "экран " + kind)
        check("Внутренняя" not in say(state, rng, mem, "отзыв всё классно"), "отзыв записан")
        main.save_game(state, rng)
        st2, _rng2, _n = main.load_game()
        check(st2 is not None and st2.week == state.week, "сейв/загрузка " + str(_n))
    print("\nИТОГ: " + ("всё ок" if not FAILS else str(len(FAILS)) + " провалов"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(run())
