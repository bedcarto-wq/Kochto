"""Баланс: боты с разными стратегиями, N сидов × 104 недели. python tests/balance_sim.py"""
from __future__ import annotations

import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main  # noqa: E402
import systems  # noqa: E402
from smoke_test import setup, end_week  # noqa: E402

BOTS = {
    "честный": ["встретиться с рабочими о зарплатах", "встретиться с пенсионерами о медицине",
                "дать интервью о медицине", "собрать пожертвования", "организовать митинг студентов",
                "помочь врачам отремонтировать больницу"],
    "грязный": ["тайно раздать деньги рабочим", "тайно собрать компромат на Воронину",
                "раскритиковать Ложкина", "поговорить с мэром и предложить деньги", "собрать пожертвования"],
    "медийный": ["дать интервью газете кочто сегодня о налогах", "раскритиковать Ложкина",
                 "выступить по телевидению о медицине", "собрать пожертвования"],
    "пассивный": [],
}


def run(seeds: int = 6, weeks: int = 104) -> None:
    with tempfile.TemporaryDirectory() as td:
        data = setup(Path(td))
        for bot, phrases in BOTS.items():
            stats = Counter()
            roles = Counter()
            t0 = time.time()
            for seed in range(seeds):
                state, rng = main.new_game(data, 1000 + seed, "Бот", 35)
                mem: dict = {}
                accepted = 0
                tried = 0
                for w in range(weeks):
                    for i in range(3 if phrases else 0):
                        tried += 1
                        msg = main.handle_command(state, rng, phrases[(w * 3 + i) % len(phrases)], mem)["message"]
                        accepted += "Принято" in msg
                    end_week(state)
                    if state.player.prison_status.value != "free":
                        stats["недель в заключении"] += 1
                    if state.is_game_over:
                        stats["смертей"] += 1
                        break
                roles[state.player.role.value] += 1
                stats["деньги"] += state.player.money
                stats["узнаваемость"] += state.player.awareness
                stats["доверие"] += state.player.trust
                stats["места"] += state.council_seats
                stats["принято%"] += int(100 * accepted / tried) if tried else 0
            print("%-10s %.1fs  роли=%s" % (bot, time.time() - t0, dict(roles)))
            print("           " + ", ".join("%s=%s" % (k, (v // seeds if k not in ("смертей",) else v))
                                          for k, v in stats.items()))


if __name__ == "__main__":
    run()
