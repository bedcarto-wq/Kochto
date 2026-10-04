import copy
import random
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gorod import engine as E  # noqa: E402
from gorod import parser as P  # noqa: E402
from gorod.engine import Card  # noqa: E402

DATA = E.load_data()
_SEEDS = iter(range(10 ** 6, 10 ** 7))
E._entropy_seed = lambda: next(_SEEDS)  # тесты не зависят от системной энтропии
SK = {"charm": 30, "eloquence": 30, "cunning": 30}


def game(seed=1, gender="m"):
    return E.new_game(DATA, "Тест Тестов", dict(SK), gender, seed=seed)


def force(state, tier="success"):
    """Подменяем бросок на нужный исход — проверяем правила, а не удачу."""
    real = E._roll

    def fake(st, data, card):
        r = real(st, data, card)
        r["tier"] = tier
        return r
    E._roll = fake
    return real


class DataTests(unittest.TestCase):
    def test_load_ok(self):
        self.assertEqual(set(DATA["groups"]), {"workers", "elders", "business"})

    def test_missing_key_is_data_error(self):
        d = copy.deepcopy(DATA)
        del d["groups"]["workers"]["salience"]["tariff_freeze"]
        with self.assertRaises(E.DataError):
            E.validate(d)

    def test_stance_range(self):
        d = copy.deepcopy(DATA)
        d["proposals"]["trade_levy"]["stance"]["elders"] = 1.5
        with self.assertRaises(E.DataError):
            E.validate(d)

    def test_press_needs_all_angles(self):
        d = copy.deepcopy(DATA)
        d["press"]["kinds"]["meeting_ok"] = [t for t in d["press"]["kinds"]["meeting_ok"] if t["angle"] != "contra"]
        with self.assertRaises(E.DataError):
            E.validate(d)

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(E.DataError):
            E.load_data(Path(tmp))


class ParserTests(unittest.TestCase):
    def card(self, text):
        return P.parse(DATA, text).card

    def test_promise_with_deadline(self):
        c = self.card("Пообещать заморозку тарифов ЖКХ за три недели")
        self.assertEqual((c.action, c.proposal, c.side, c.deadline), ("promise", "tariff_freeze", 1, 3))

    def test_negative_side(self):
        for text in ("выступить против расширения завода", "заявить, что не допущу расширения завода",
                     "заявить: тарифы не будут заморожены"):
            self.assertEqual(self.card(text).side, -1, text)

    def test_interview_paper(self):
        c = self.card("дать интервью Голосу улицы")
        self.assertEqual((c.action, c.paper), ("interview", "opposition"))

    def test_longest_stem_wins(self):
        c = self.card("встретиться с заводчанами")
        self.assertEqual((c.action, c.group, c.proposal), ("meeting", "workers", ""))

    def test_voting_is_not_newspaper(self):
        c = self.card("добиться голосования в совете по тарифам")
        self.assertEqual((c.action, c.paper, c.proposal), ("initiative", "", "tariff_freeze"))

    def test_multi_action_is_one_card_with_note(self):
        r = P.parse(DATA, "встретиться с пенсионерами и пообещать заморозку тарифов")
        self.assertEqual(r.card.action, "promise")
        self.assertTrue(any("несколько действий" in n for n in r.notes))

    def test_guess_and_unknown(self):
        r = P.parse(DATA, "пенсионеры")
        self.assertTrue(r.guessed)
        self.assertIsNone(P.parse(DATA, "погода хорошая").card)


class RuleTests(unittest.TestCase):
    def setUp(self):
        self._real = force(None)

    def tearDown(self):
        E._roll = self._real

    def test_keyword_stuffing_gives_nothing_extra(self):
        short, long_ = game(5), game(5)
        E.perform(short, DATA, P.parse(DATA, "пообещать заморозку тарифов").card)
        E.perform(long_, DATA, P.parse(DATA, "публично и тайно пообещать заморозку тарифов, деньги, "
                                             "секретно, гарантирую, клянусь, тарифы ЖКХ квартплата").card)
        self.assertEqual(E.to_dict(short)["groups"], E.to_dict(long_)["groups"])

    def test_rule_error_keeps_state(self):
        s = game()
        s.money = 10
        before = E.to_dict(s)
        with self.assertRaises(E.RuleError):
            E.perform(s, DATA, Card("initiative", proposal="trade_levy", side=1))
        self.assertEqual(before, E.to_dict(s))

    def test_repeat_is_weaker(self):
        s = game()
        r1 = E.perform(s, DATA, Card("statement", proposal="tariff_freeze", side=1))
        r2 = E.perform(s, DATA, Card("statement", proposal="tariff_freeze", side=1))
        self.assertLess(r2["facts"][0].deltas["elders.support"], r1["facts"][0].deltas["elders.support"])
        self.assertEqual(r2["facts"][0].kind, "statement_weak")

    def test_flip_flop_costs_trust_everywhere(self):
        s = game()
        E.perform(s, DATA, Card("statement", proposal="plant_expansion", side=1))
        t0 = {g: v.trust for g, v in s.groups.items()}
        out = E.perform(s, DATA, Card("statement", proposal="plant_expansion", side=-1))
        self.assertIn("flip_flop", [f.kind for f in out["facts"]])
        self.assertTrue(all(s.groups[g].trust < t0[g] for g in s.groups))

    def test_promise_breaks_after_deadline(self):
        s = game()
        E.perform(s, DATA, Card("promise", proposal="tariff_freeze", side=1, deadline=2))
        trust = s.groups["elders"].trust
        E.end_week(s, DATA)
        self.assertEqual(s.promises[0].status, "open")
        E.end_week(s, DATA)
        self.assertEqual(s.promises[0].status, "broken")
        self.assertLess(s.groups["elders"].trust, trust)
        self.assertIn("promise_broken", [f.kind for f in s.facts])

    def test_promise_kept_by_initiative(self):
        s = game()
        E.perform(s, DATA, Card("promise", proposal="tariff_freeze", side=1, deadline=3))
        out = E.perform(s, DATA, Card("initiative", proposal="tariff_freeze", side=1))
        self.assertEqual(s.promises[0].status, "kept")
        self.assertIn("promise_kept", [f.kind for f in out["facts"]])
        with self.assertRaises(E.RuleError):
            E.perform(s, DATA, Card("initiative", proposal="tariff_freeze", side=1))

    def test_broken_promise_weakens_future_words(self):
        a, b = game(3), game(3)
        E.perform(a, DATA, Card("promise", proposal="trade_levy", side=1, deadline=1))
        E.end_week(a, DATA)
        b.week_seeds = list(a.week_seeds)
        b.week = a.week
        ra = E.perform(a, DATA, Card("statement", proposal="tariff_freeze", side=1))
        rb = E.perform(b, DATA, Card("statement", proposal="tariff_freeze", side=1))
        self.assertLess(ra["facts"][0].deltas["elders.support"], rb["facts"][0].deltas["elders.support"])

    def test_rival_attacks_sins(self):
        d = copy.deepcopy(DATA)
        d["rival"]["attack_chance"] = 1.0
        s = game()
        E.perform(s, d, Card("promise", proposal="tariff_freeze", side=1, deadline=1))
        E.end_week(s, d)  # обещание сорвано
        E.end_week(s, d)  # соперник вспоминает
        self.assertIn("rival_attack", [f.kind for f in s.facts])


class ElectionTests(unittest.TestCase):
    def test_group_support_decides(self):
        s = game()
        rng = random.Random(1)
        low = E.election(s, DATA, rng)
        for g in s.groups.values():
            g.support_player = 80
        high = E.election(s, DATA, random.Random(1))
        self.assertFalse(low["won"])
        self.assertTrue(high["won"])
        self.assertEqual({r["group"] for r in high["rows"]}, set(DATA["groups"]))

    def test_election_happens_and_game_continues(self):
        s = game()
        for _ in range(DATA["meta"]["election_week"]):
            rep = E.end_week(s, DATA)
        self.assertIsNotNone(rep["election"])
        self.assertEqual(len(s.elections), 1)
        self.assertGreater(s.next_election_week, s.week)


class DeterminismTests(unittest.TestCase):
    def script(self, s):
        cards = [Card("meeting", group="workers"), Card("promise", proposal="tariff_freeze", side=1, deadline=4),
                 Card("interview", paper="opposition", proposal="plant_expansion", side=1)]
        for c in cards:
            E.perform(s, DATA, copy.deepcopy(c))
        return E.end_week(s, DATA)

    def test_same_seed_same_world(self):
        a, b = game(42), game(42)
        ra, rb = self.script(a), self.script(b)
        self.assertEqual([x["headline"] for x in ra["articles"]], [x["headline"] for x in rb["articles"]])
        a.week_seeds[-1] = b.week_seeds[-1]
        self.assertEqual(E.to_dict(a), E.to_dict(b))

    def test_save_load_roundtrip(self):
        s = game(9)
        self.script(s)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "slot.json"
            E.save_game(s, path)
            self.assertEqual(E.to_dict(E.load_game(path)), E.to_dict(s))

    def test_bad_save_is_data_error(self):
        with self.assertRaises(E.DataError):
            E.from_dict({"schema_version": 999})


class PressTests(unittest.TestCase):
    def test_articles_are_about_this_week_facts(self):
        s = game(11, gender="f")
        E.perform(s, DATA, Card("promise", proposal="trade_levy", side=-1, deadline=4))
        rep = E.end_week(s, DATA)
        ids = {f.id for f in s.facts if f.week == 1}
        self.assertEqual(len(rep["articles"]), len(DATA["papers"]))
        for a in rep["articles"]:
            self.assertIn(a["fact_id"], ids)
            self.assertIsNone(re.search(r"[{}]", a["headline"] + a["lead"]))
            self.assertNotIn("Тест Тестов дал ", a["headline"] + a["lead"])  # женский род

    def test_no_immediate_repeats(self):
        s = game(12)
        seen = []
        for _ in range(3):
            E.perform(s, DATA, Card("meeting", group="elders"))
            rep = E.end_week(s, DATA)
            seen += [a["template"] for a in rep["articles"] if a["paper"] == "opposition"]
        self.assertEqual(len(seen), len(set(seen)))


class BalanceSmoke(unittest.TestCase):
    def test_work_beats_idling(self):
        def run(active, seed):
            s = game(seed)
            rng = random.Random(seed)
            while not s.elections:
                if active:
                    for c in (Card("promise", proposal="tariff_freeze", side=1, deadline=5),
                              Card("initiative", proposal="tariff_freeze", side=1),
                              Card("meeting", group=rng.choice(["workers", "elders"]))):
                        try:
                            E.perform(s, DATA, c)
                        except E.RuleError:
                            E.perform(s, DATA, Card("interview", paper="opposition"))
                E.end_week(s, DATA)
            e = s.elections[0]
            return e["player"] / (e["player"] + e["rival"])
        idle = sum(run(False, i) for i in range(20)) / 20
        work = sum(run(True, i) for i in range(20)) / 20
        self.assertGreater(work, idle + 0.15)


if __name__ == "__main__":
    unittest.main()
