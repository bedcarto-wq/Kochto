"""Обучение ИИ (отложенная выборка, подстройка в игре), обещания, совет, режимы ввода, диаграмма выборов."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gorod import engine as E  # noqa: E402
from gorod import improver as I  # noqa: E402
from gorod import nlu  # noqa: E402
from gorod import parser as P  # noqa: E402
from gorod.engine import Card  # noqa: E402
from gorod.session import Session, ascii_chart  # noqa: E402

DATA = E.load_data()
_SEEDS = iter(range(2 * 10 ** 6, 10 ** 7))
E._entropy_seed = lambda: next(_SEEDS)
SK = {"charm": 30, "eloquence": 30, "cunning": 30}
PHRASES = json.loads((Path(E.__file__).parent / "data" / "train_phrases.json").read_text(encoding="utf-8"))["phrases"]


def game(seed=1):
    return E.new_game(DATA, "Тест Тестов", dict(SK), "m", seed=seed)


class HeldOutTests(unittest.TestCase):
    def test_split_exists_and_is_disjoint(self):
        test = [p for p in PHRASES if p["split"] == "test"]
        train = {p["text"] for p in PHRASES if p["split"] == "train"}
        self.assertGreaterEqual(len(test), 30)
        self.assertFalse(train & {p["text"] for p in test})

    def test_held_out_accuracy(self):
        """Модель не видела эти фразы. Замер: NB ≈ 91%, разборщик целиком ≈ 97%."""
        test = [p for p in PHRASES if p["split"] == "test"]
        nb = sum(1 for p in test if (lambda pr: pr and max(pr, key=pr.get) == p["action"])(
            DATA["_nlu"].predict(nlu.tokens(p["text"]))))
        full = sum(1 for p in test if (lambda c: c and c.action == p["action"])(P.parse(DATA, p["text"]).card))
        self.assertGreaterEqual(nb / len(test), 0.8)
        self.assertGreaterEqual(full / len(test), 0.9)


class OnlineLearningTests(unittest.TestCase):
    def test_correction_is_remembered(self):
        s = Session(DATA)
        s.new("Тест Тестов", "m", dict(SK), seed=3)
        text = "Нельзя перекладывать ремонт дорог на плечи лавочников"
        s.understand(text)
        s.set_action("statement")
        s.set_slot("proposal", "trade_levy")
        s.set_slot("side", -1)
        s.confirm()
        self.assertEqual(s.state.learned[-1], [text, "statement"])
        v = s.understand(text)
        self.assertEqual(v["action"], "statement")
        self.assertEqual(v["source"], "память")

    def test_learned_cap(self):
        st = game()
        for i in range(int(DATA["tuning"]["learned_cap"]) + 20):
            E.learn(st, DATA, "фраза " + str(i), "meeting")
        self.assertEqual(len(st.learned), int(DATA["tuning"]["learned_cap"]))
        E.learn(st, DATA, "  ", "meeting")
        E.learn(st, DATA, "текст", "нет_такого")
        self.assertEqual(st.learned[-1][0], "фраза " + str(int(DATA["tuning"]["learned_cap"]) + 19))

    def test_learned_shifts_model(self):
        learned = [["созвать пикет у мэрии", "publicize"]] * 3
        pr = P.model(DATA, learned).predict(nlu.tokens("созвать пикет у мэрии"))
        base = DATA["_nlu"].predict(nlu.tokens("созвать пикет у мэрии"))
        self.assertGreater(pr["publicize"], (base or {}).get("publicize", 0.0))


class PromiseTests(unittest.TestCase):
    def test_promise_pile(self):
        st = game()
        self.assertEqual(E.promise_pile(st, DATA), 1.0)
        for i in range(2):
            st.promises.append(E.Promise(id="p" + str(i), proposal="tariff_freeze", side=1, made_week=1,
                                         deadline_week=5, groups=[]))
        self.assertAlmostEqual(E.promise_pile(st, DATA), 1 / (1 + 2 * DATA["tuning"]["promise_pile"]))

    def test_repromise_after_broken_hurts(self):
        st = game()
        st.promises.append(E.Promise(id="p1", proposal="tariff_freeze", side=1, made_week=1, deadline_week=1,
                                     groups=["elders"], status="broken"))
        card = Card(action="promise", proposal="tariff_freeze", side=1, deadline=4)
        self.assertTrue(any("обещ" in w.lower() for w in E.warnings(st, DATA, card)))
        st2 = game()
        t1, t2 = st.groups["elders"].trust, st2.groups["elders"].trust
        roll = {"tier": "success", "roll": 60, "total": 70, "difficulty": 50}
        E._do_promise(st, DATA, card, roll, 1.0)
        E._do_promise(st2, DATA, card, roll, 1.0)
        self.assertLess(st.groups["elders"].trust - t1, st2.groups["elders"].trust - t2)
        self.assertTrue(st.facts[-1].extra.get("again"))


class ZeroSumTests(unittest.TestCase):
    def test_gain_takes_from_rival(self):
        st = game()
        f = E._fact(st, "test", "player", 1, 1.0)
        r0 = st.groups["workers"].support_rival
        E._apply(st, DATA, f, "workers", support=10.0)
        self.assertAlmostEqual(st.groups["workers"].support_rival, E.clamp(r0 - 10 * DATA["tuning"]["zero_sum"]))


class CouncilTests(unittest.TestCase):
    def test_dhondt(self):
        self.assertEqual(E.dhondt({"a": 55, "b": 30, "c": 15}, 9, 0.05), {"a": 5, "b": 3, "c": 1})
        seats = E.dhondt({"a": 60, "b": 30, "c": 7, "d": 3}, 9, 0.05)
        self.assertEqual(sum(seats.values()), 9)
        self.assertEqual(seats["d"], 0)  # ниже порога
        self.assertGreater(seats["a"], seats["b"])

    def test_council_vote_sums(self):
        co = E.council_vote(game(), DATA, None)
        self.assertEqual(sum(co["seats"].values()), DATA["council"]["seats"])
        self.assertAlmostEqual(sum(co["share"].values()), 1.0, places=2)

    def test_seats_lower_initiative_difficulty(self):
        st = game()
        card = Card(action="initiative", proposal="tariff_freeze", side=1)
        d0 = E.difficulty(st, DATA, card)
        st.council["player"] = 3
        self.assertEqual(E.difficulty(st, DATA, card), d0 - 3 * DATA["council"]["seat_bonus"])


class ImproverTests(unittest.TestCase):
    def test_round_trip(self):
        for text in ["пообещаю рабочим завод", "встреча с пенсионерами", "интервью вестнику про тарифы против",
                     "заявляю что против сбора"]:
            vs = I.improve(DATA, text)
            self.assertTrue(vs, text)
            for v in vs:
                c = P.parse(DATA, v["text"]).card
                self.assertIsNotNone(c, v["text"])
                self.assertEqual(c.action, v["action"], v["text"])

    def test_phrase_of_card(self):
        c = Card(action="promise", proposal="tariff_freeze", side=-1, deadline=3)
        back = P.parse(DATA, I.phrase(DATA, c)).card
        self.assertEqual((back.action, back.proposal, back.side, back.deadline), ("promise", "tariff_freeze", -1, 3))


class ModeTests(unittest.TestCase):
    def setUp(self):
        self.s = Session(DATA)
        self.s.new("Тест Тестов", "m", dict(SK), seed=5)

    def test_modes(self):
        for m in ("text", "improver", "card"):
            self.s.set_mode(m)
        with self.assertRaises(E.RuleError):
            self.s.set_mode("телепатия")

    def test_manual_card(self):
        self.s.set_mode("card")
        v = self.s.manual("meeting")
        self.assertFalse(v["ready"])
        v = self.s.set_slot("group", "workers")
        self.assertTrue(v["ready"])
        self.assertEqual(v["source"], "карточка")
        n = len(self.s.state.learned)
        self.s.confirm()
        self.assertEqual(len(self.s.state.learned), n)  # без текста учить нечему
        with self.assertRaises(E.RuleError):
            self.s.manual("полёт")

    def test_deadline(self):
        self.s.manual("promise")
        self.assertEqual(self.s.set_deadline(6)["deadline"], 6)
        self.s.manual("meeting")
        with self.assertRaises(E.RuleError):
            self.s.set_deadline(3)


class ChartTests(unittest.TestCase):
    def test_forecast_chart(self):
        s = Session(DATA)
        s.new("Тест Тестов", "m", dict(SK), seed=7)
        ch = s.forecast_chart()
        self.assertAlmostEqual(sum(p for _, p in ch["mayor"]), 100.0, delta=0.2)
        self.assertEqual(len(ch["groups"]), len(DATA["groups"]))
        self.assertEqual(sum(k for _, _, k in ch["council"]), DATA["council"]["seats"])
        self.assertTrue(ch["caption"].startswith("Прогноз. Мэр:"))
        self.assertIn("Мандаты совета (9)", ch["caption"])
        lines = ascii_chart(ch)
        self.assertEqual(lines[-1], ch["caption"])

    def test_election_week_has_chart(self):
        s = Session(DATA)
        s.new("Тест Тестов", "m", dict(SK), seed=8)
        rep = None
        while not s.over and s.state.week <= s.state.next_election_week:
            rep = s.end_week()
            if rep["election"]:
                break
        if not s.over:
            self.assertIn("chart", rep)
            self.assertEqual(s.state.council, rep["election"]["council"]["seats"])


if __name__ == "__main__":
    unittest.main()
