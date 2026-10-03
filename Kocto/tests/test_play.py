"""Interactive tutorial, dirty actions with traces, rival ratings (fake engine)."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_world as contract
from campaign_play import PlayRuntime, load_config, TRACES, TUTORIAL

ROOT = Path(__file__).resolve().parents[1]


class PlayTests(contract.WorldTests):
    def setUp(self):
        super().setUp()
        self.runtime.uninstall()
        self.config = load_config(ROOT / 'data/world/semantic.json')
        self.config['situation_chance'] = 0
        self.config['passivity']['grace_weeks'] = 999
        self.config['dirty']['weekly_discovery'] = 0
        self.runtime = PlayRuntime(self.engine, self.config)
        self.runtime.install()
        self.state.player.evidence = 0
        self.state.player.investigation = 0

    def test_unknown_and_dirty_do_not_fall_back(self):
        for phrase in ('лететь на луну', 'подкупить рабочих', 'незаконно пообещать рабочим бороться за зарплаты'):
            self.say(phrase)
            self.assertFalse(self.state.week_actions)
        self.assertFalse(self.legacy_calls)

    def test_dirty_meeting_is_stronger_costs_more_and_explained(self):
        clean = self.runtime.evaluate(self.state, self.card('встретиться с рабочими о работе'))
        self.say('отменить карточку')
        text = self.say('незаконно встретиться с рабочими о работе')
        self.assertIn('ГРЯЗНЫЙ МЕТОД', text)
        dirty = self.runtime.evaluate(self.state, self.card('незаконно встретиться с рабочими о работе'))
        self.assertGreaterEqual(dirty[0].effect, round(clean[0].effect * 1.5, 3) - 0.01)
        self.assertEqual(dirty[1], clean[1] + 300)
        self.assertLessEqual(dirty[0].chance, 90)
        self.assertIn('dirty', [r.source for r in dirty[0].reasons])

    def test_clean_actions_leave_no_traces(self):
        self.accept()
        self.week()
        self.assertFalse(self.state.world.get(TRACES))
        self.assertIn('Улик против тебя нет', self.say('улики'))

    def test_secret_trace_smaller_and_fades(self):
        self.accept('тайно незаконно встретиться с рабочими о работе')
        self.week()
        trace = self.state.world[TRACES][0]
        self.assertEqual((trace['status'], trace['strength']), ('hidden', 0.25))
        self.week()
        self.assertLess(self.state.world[TRACES][0]['strength'], 0.25)
        self.assertIn('Риск разоблачения', self.say('улики'))

    def test_exposure_is_delayed_and_punishes_once(self):
        self.runtime.config['dirty']['weekly_discovery'] = 10
        self.runtime.config['dirty']['max_discovery'] = 1
        self.state.candidates.append(NS(id='lozhkin', name='Ложкин', popularity=10))
        self.accept('незаконно встретиться с рабочими о работе')
        trust = self.state.player.trust
        self.week()  # the trace is created now, found only later
        self.assertEqual(self.state.world[TRACES][0]['status'], 'hidden')
        self.week()
        self.assertEqual(self.state.world[TRACES][0]['status'], 'exposed')
        scandal = [c for c in self.state.clippings if c['source'] == 'semantic_dirty']
        self.assertEqual(len(scandal), 1)
        self.assertEqual(self.state.player.trust, trust - 6)
        self.assertEqual(self.state.player.evidence, 10)
        self.assertEqual(self.state.candidates[0].popularity, 13)
        self.week()
        self.assertEqual(len([c for c in self.state.clippings if c['source'] == 'semantic_dirty']), 1)

    def test_cleanup_costs_money_once_per_week(self):
        self.accept('незаконно встретиться с рабочими о работе')
        self.week()
        money = self.state.player.money
        self.assertIn('Следы заметены', self.say('замести следы'))
        self.assertEqual(self.state.player.money, money - 400)
        self.assertIn('уже заметали', self.say('замести следы'))

    def test_rival_rating_gains_on_exploit(self):
        self.state.candidates.append(NS(id='lozhkin', name='Ложкин', popularity=10))
        self.groups[0].candidate_support = {}
        self.groups[0].size = 100
        self.accept('встретиться с рабочими за сокращения')
        self.week(0)
        self.assertEqual(self.state.candidates[0].popularity, 12)
        self.assertEqual(self.groups[0].candidate_support['lozhkin'], 2)
        self.assertIn('рейтинг 12', self.say('рейтинги'))

    def test_won_debate_lowers_rival(self):
        self.state.candidates.append(NS(id='lozhkin', name='Ложкин', popularity=10))
        self.accept('встретиться с рабочими против сокращений')
        self.week(100)
        self.assertEqual(self.state.candidates[0].popularity, 8)

    def test_interactive_tutorial_walkthrough(self):
        state, _ = self.engine.new_game()
        self.assertTrue(state.world[TUTORIAL]['active'])
        self.state.world[TUTORIAL] = {'step': 0, 'active': True}
        self.assertIn('Обучение 1/7', self.say('обучение'))
        self.assertIn('Обучение 2/7', self.say('досье рабочие'))
        self.assertIn('Обучение 3/7', self.say('встретиться с рабочими о работе'))
        self.assertIn('Обучение 4/7', self.say('подтвердить действие'))
        self.assertIn('Обучение 5/7', self.say('ситуации'))
        self.week()
        self.assertTrue(any('Обучение 6/7' in line for line in self.logs))
        self.say('пообещать рабочим бороться против сокращений')
        self.assertIn('Обучение 7/7', self.say('подтвердить действие'))
        self.assertIn('Обучение пройдено', self.say('улики'))
        self.assertNotIn('Обучение', self.say('советник'))
        self.assertIn('выключено', self.say('обучение выкл'))
        self.assertIn('Обучение 1/7', self.say('обучение заново'))

    def test_tutorial_text_has_no_broken_characters(self):
        for line in self.config['tutorial'] + [s['text'] for s in self.config['tutorial_steps']]:
            self.assertNotIn('\ufffd', line)


del contract

if __name__ == '__main__':
    unittest.main()
