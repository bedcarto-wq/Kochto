"""ИИ понимания, ИИ соперника, угрозы и смерть, сценарий хода для окна."""
import copy
import json
import random
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gorod import engine as E  # noqa: E402
from gorod import nlu, rival_ai  # noqa: E402
from gorod import parser as P  # noqa: E402
from gorod.engine import Card  # noqa: E402
from gorod.session import Session  # noqa: E402

DATA = E.load_data()
_SEEDS = iter(range(10 ** 6, 10 ** 7))
E._entropy_seed = lambda: next(_SEEDS)  # тесты не зависят от системной энтропии
SK = {"charm": 30, "eloquence": 30, "cunning": 30}


def game(seed=1):
    return E.new_game(DATA, "Тест Тестов", dict(SK), "m", seed=seed)


class Forced:
    """Контекст: все броски дают нужный исход."""
    def __init__(self, tier="success"):
        self.tier = tier

    def __enter__(self):
        self.real = E._roll

        def fake(st, data, card):
            r = self.real(st, data, card)
            r["tier"] = self.tier
            return r
        E._roll = fake

    def __exit__(self, *a):
        E._roll = self.real


def data_with(**patch):
    d = {k: copy.deepcopy(v) for k, v in DATA.items() if k != "_nlu"}
    d["_nlu"] = DATA["_nlu"]
    for path, val in patch.items():
        node = d
        keys = path.split("__")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = val
    return d


class NluTests(unittest.TestCase):
    def test_leave_one_out_accuracy(self):
        ph = json.loads((E.DATA_DIR / "train_phrases.json").read_text(encoding="utf-8"))["phrases"]
        ok = 0
        for i, p in enumerate(ph):
            m = nlu.NaiveBayes().fit([(q["text"], q["action"]) for j, q in enumerate(ph) if j != i])
            pr = m.predict(nlu.tokens(p["text"]))
            ok += bool(pr) and max(pr, key=pr.get) == p["action"]
        self.assertGreaterEqual(ok / len(ph), 0.75)

    def test_free_wording_understood_by_ai(self):
        r = P.parse(DATA, "посидеть с бабушками на лавочке")
        self.assertEqual((r.card.action, r.card.group, r.source), ("meeting", "elders", "ИИ"))
        r = P.parse(DATA, "протолкнуть через депутатов заморозку тарифов")
        self.assertEqual((r.card.action, r.source), ("initiative", "ИИ"))

    def test_typo_is_fixed_and_reported(self):
        r = P.parse(DATA, "встретиться с пенсонерами")
        self.assertEqual(r.card.group, "elders")
        self.assertTrue(any("опечатк" in n for n in r.notes))

    def test_no_false_typo_on_short_stems(self):
        r = P.parse(DATA, "пожаловаться в прокуратуру")
        self.assertEqual((r.card.action, r.card.group), ("publicize", ""))

    def test_stem(self):
        self.assertEqual(nlu.stem("встретиться"), nlu.stem("встретить"))

    def test_bad_corpus_is_data_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            for f in E.DATA_DIR.iterdir():
                if f.is_dir():
                    shutil.copytree(f, Path(tmp) / f.name)
                else:
                    shutil.copy(f, tmp)
            (Path(tmp) / "train_phrases.json").write_text(
                json.dumps({"phrases": [{"text": "x", "action": "dance"}]}), encoding="utf-8")
            with self.assertRaises(E.DataError):
                E.load_data(Path(tmp))
            (Path(tmp) / "train_phrases.json").unlink()
            with self.assertRaises(E.DataError):
                E.load_data(Path(tmp))


class ThreatTests(unittest.TestCase):
    def test_initiative_makes_enemy(self):
        s = game()
        with Forced():
            E.perform(s, DATA, Card("initiative", proposal="plant_expansion", side=-1))
        self.assertGreater(s.threat, 0)
        self.assertEqual(E.top_enemy(s), "plant_owner")

    def test_warning_when_threat_grows(self):
        s = game()
        s.threat = 35
        s.threat_sources = {"market_bosses": 35}
        E.end_week(s, DATA)
        warn = [f for f in s.facts if f.kind == "threat_warning"]
        self.assertEqual(len(warn), 1)
        self.assertEqual(warn[0].extra["enemy"], "market_bosses")

    def test_security_and_upkeep(self):
        s = game()
        with Forced():
            E.perform(s, DATA, Card("security"))
        self.assertEqual(s.security, 1)
        money = s.money
        rep = E.end_week(s, DATA)
        upkeep = DATA["actions"]["security"]["upkeep_per_level"]
        self.assertEqual(s.money, money + rep["income"] - upkeep)

    def test_publicize_without_threat_is_panic(self):
        s = game()
        with Forced():
            out = E.perform(s, DATA, Card("publicize"))
        self.assertEqual(out["facts"][0].kind, "publicize_panic")

    def test_publicize_cuts_threat(self):
        s = game()
        s.threat, s.threat_sources = 50, {"rival_circle": 50}
        with Forced():
            E.perform(s, DATA, Card("publicize"))
        self.assertLess(s.threat, 50)

    def test_death_ends_game(self):
        d = data_with(threat__attack_scale=100.0, threat__attack_floor=0.0, threat__death_below=1000.0)
        s = game()
        s.threat = 90
        rep = E.end_week(s, d)
        self.assertTrue(s.dead and rep["dead"])
        covered = {a["fact_id"] for a in rep["articles"]}
        self.assertTrue(any(f.kind == "death" and f.id in covered for f in s.facts))
        with self.assertRaises(E.RuleError):
            E.perform(s, d, Card("meeting", group="workers"))
        with self.assertRaises(E.RuleError):
            E.end_week(s, d)

    def test_injury_costs_actions(self):
        d = data_with(threat__attack_scale=100.0, threat__attack_floor=0.0, threat__death_below=-1.0,
                      threat__injury_below=1000.0)
        s = game()
        s.threat = 90
        E.end_week(s, d)
        self.assertEqual(s.actions_left, DATA["meta"]["actions_per_week"] - 1)

    def test_security_lowers_attack_odds(self):
        def attacks(sec):
            n = 0
            for seed in range(1, 150):
                s = game(seed)
                s.threat, s.security, s.money = 80, sec, 10 ** 6
                E.end_week(s, DATA)
                n += any(f.kind.startswith("attack") or f.kind == "death" for f in s.facts)
            return n
        self.assertLess(attacks(2), attacks(0))


class RivalAiTests(unittest.TestCase):
    def test_options_and_reason(self):
        s = game()
        kinds = {o.kind for o in rival_ai.options(s, DATA)}
        self.assertEqual(kinds, {"meet"})
        E.end_week(s, DATA)
        f = next(f for f in s.facts if f.actor == "rival")
        self.assertTrue(f.extra["why"])

    def test_steals_popular_position_once(self):
        s = game()
        s.positions["tariff_freeze"] = 1
        opts = [o for o in rival_ai.options(s, DATA) if o.kind == "steal"]
        self.assertEqual([o.proposal for o in opts], ["tariff_freeze"])
        opt = opts[0]
        opt.value = 10 ** 9
        real = rival_ai.plan
        rival_ai.plan = lambda st, d, rng: opt
        try:
            E.end_week(s, DATA)
        finally:
            rival_ai.plan = real
        self.assertEqual(s.rival_positions["tariff_freeze"], 1)
        self.assertFalse([o for o in rival_ai.options(s, DATA) if o.kind == "steal"])

    def test_dirty_only_when_losing_late(self):
        s = game()
        for g in s.groups.values():
            g.support_player = 90
        self.assertFalse({"compromat", "threat"} & {o.kind for o in rival_ai.options(s, DATA)})
        s.week = DATA["rival"]["dirty_after_week"]
        self.assertTrue({"compromat", "threat"} <= {o.kind for o in rival_ai.options(s, DATA)})

    def test_plan_is_best_value(self):
        s = game()
        opts = rival_ai.options(s, DATA)
        best = rival_ai.plan(s, DATA, random.Random(1))
        self.assertGreaterEqual(best.value, max(o.value for o in opts) - 1.0)

    def test_meeting_fatigue(self):
        s = game()
        with Forced():
            a = E.perform(s, DATA, Card("meeting", group="elders"))["facts"][0].deltas["elders.support"]
            b = E.perform(s, DATA, Card("meeting", group="elders"))["facts"][0].deltas["elders.support"]
        self.assertLess(b, a)


class SessionTests(unittest.TestCase):
    def test_flow(self):
        ses = Session(DATA)
        ses.new("Анна Корнилова", "f", dict(SK), seed=4)
        v = ses.understand("дать интервью")
        self.assertEqual(v["missing"], ["paper"])
        self.assertFalse(v["ready"])
        v = ses.set_slot("paper", "opposition")
        self.assertTrue(v["ready"])
        lines = ses.confirm()
        self.assertTrue(lines[0].startswith("Бросок"))
        st = ses.status()
        self.assertEqual(st["actions_left"], 2)
        self.assertIn("player", st["forecast"])
        rep = ses.end_week()
        self.assertTrue(rep["lines"][0].startswith("— Итоги недели 1"))
        for a in rep["articles"]:
            self.assertIsNone(re.search(r"[{}]", a["headline"] + a["lead"]))

    def test_bad_slot(self):
        ses = Session(DATA)
        ses.new("Иван", "m", dict(SK), seed=1)
        ses.understand("встретиться")
        with self.assertRaises(E.RuleError):
            ses.set_slot("group", "aliens")

    def test_save_load(self):
        ses = Session(DATA)
        ses.new("Иван", "m", dict(SK), seed=2)
        ses.end_week()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "s.json"
            ses.save(p)
            other = Session(DATA)
            other.load(p)
            self.assertEqual(E.to_dict(other.state), E.to_dict(ses.state))


class DeterminismV2(unittest.TestCase):
    def test_full_campaign_reproducible(self):
        def run():
            s = game(77)
            rng = random.Random(5)
            heads = []
            while not s.elections and not s.dead:
                for _ in range(s.actions_left):
                    c = rng.choice([Card("meeting", group="elders"), Card("statement", proposal="tariff_freeze", side=1),
                                    Card("initiative", proposal="trade_levy", side=1), Card("interview", paper="official")])
                    try:
                        E.perform(s, DATA, c)
                    except E.RuleError:
                        pass
                seeds = list(s.week_seeds)
                rep = E.end_week(s, DATA)
                s.week_seeds[-1] = seeds[-1] * 7 + 1  # фиксируем «энтропию» новой недели
                heads += [a["headline"] for a in rep["articles"]]
            return heads, E.to_dict(s)
        self.assertEqual(run(), run())


if __name__ == "__main__":
    unittest.main()
