"""Dossiers, red lines and press on the fake engine; inherits all runtime contracts."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_semantic_runtime as contract
from dossiers import DossierRuntime, load_config

ROOT = Path(__file__).resolve().parents[1]


class DossierTests(contract.RuntimeTests):
    def setUp(self):
        super().setUp()
        self.runtime.uninstall()
        self.config = load_config(ROOT / 'data/world/semantic.json')
        self.runtime = DossierRuntime(self.engine, self.config)
        self.runtime.install()

    def test_promise_broken_by_opposite_stance_once(self):
        self.accept('пообещать рабочим бороться против сокращений')
        self.week()
        trust = self.state.player.trust
        self.accept('встретиться с рабочими за сокращения')
        self.week()
        self.assertEqual(self.state.world['semantic_promises'][0]['status'], 'broken')
        # -3 broken promise, -2 because this stance is also the workers' red line.
        self.assertEqual(self.state.player.trust, trust - 5)
        self.week()
        self.assertEqual(self.state.player.trust, trust - 5)

    def test_dossier_command(self):
        text = self.say('досье рабочие')
        self.assertIn('Красная линия: поддержка сокращений', text)
        self.assertIn('Опасение', text)
        self.assertIn('Досье есть', self.say('досье'))
        self.assertIn('Нет досье', self.say('досье марсиане'))
        self.assertFalse(self.legacy_calls)

    def test_red_line_lowers_chance_flips_effect_and_warns(self):
        normal = self.runtime.evaluate(self.state, self.card('встретиться с рабочими против сокращений'))[0]
        crossing = self.runtime.evaluate(self.state, self.card('встретиться с рабочими за сокращения'))[0]
        self.assertLess(crossing.chance, normal.chance)
        self.assertGreaterEqual(crossing.chance, 15)
        self.assertLess(crossing.effect, 0)
        self.assertIn('red_line', [r.source for r in crossing.reasons])
        self.assertIn('ВНИМАНИЕ', self.say('встретиться с рабочими за сокращения'))

    def test_fear_reduces_effect_not_chance(self):
        plain = self.runtime.evaluate(self.state, self.card('встретиться с рабочими о зарплате'))[0]
        afraid = self.runtime.evaluate(self.state, self.card('встретиться с рабочими против зарплаты'))[0]
        self.assertIn('fear', [r.source for r in afraid.reasons])
        self.assertNotIn('fear', [r.source for r in plain.reasons])

    def test_public_red_line_published_once(self):
        self.accept('встретиться с рабочими за сокращения')
        trust, mood, clips = self.state.player.trust, self.groups[0].mood, len(self.state.clippings)
        self.week(0)
        self.assertEqual(self.state.player.trust, trust - 2)
        self.assertLessEqual(self.groups[0].mood, mood - 5)
        press = [c for c in self.state.clippings[clips:] if c['source'] == 'semantic_press']
        self.assertEqual(len(press), 1)
        self.assertEqual(press[0]['publication'], 'opposition')
        self.week(0)
        self.assertEqual(self.state.player.trust, trust - 2)

    def test_secret_red_line_penalised_without_press(self):
        self.accept('тайно встретиться с рабочими за сокращения')
        trust, clips = self.state.player.trust, len(self.state.clippings)
        self.week(0)
        self.assertEqual(self.state.player.trust, trust - 2)
        self.assertFalse([c for c in self.state.clippings[clips:] if c['source'] == 'semantic_press'])

    def test_broken_promise_published_once(self):
        self.accept('пообещать рабочим бороться за зарплаты')
        for _ in range(11):
            self.week()
        self.assertEqual(sum(c['headline'] == 'Обещание не выполнено' for c in self.state.clippings), 1)


del contract  # keep the base class from being collected twice

if __name__ == '__main__':
    unittest.main()
