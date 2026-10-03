"""City situations, rival replies, passivity, advisor and tutorial (fake engine)."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_dossiers as contract
from campaign_world import WorldRuntime, load_config

ROOT = Path(__file__).resolve().parents[1]
NAMES = {'youth': 'Молодёжь', 'elders': 'Пенсионеры', 'teachers': 'Учителя', 'doctors': 'Врачи'}


class WorldTests(contract.DossierTests):
    def setUp(self):
        super().setUp()
        self.runtime.uninstall()
        self.config = load_config(ROOT / 'data/world/semantic.json')
        self.config['situation_chance'] = 0  # inherited contracts run in a calm city
        self.config['passivity']['grace_weeks'] = 999
        self.runtime = WorldRuntime(self.engine, self.config)
        self.runtime.install()

    def all_groups(self):
        for gid, name in NAMES.items():
            self.state.groups.append(NS(id=gid, name=name, issues={}, mood=50))

    def force(self, situation_id):
        self.runtime.config['situation_chance'] = 1
        self.runtime.config['situations'] = [s for s in self.config['situations'] if s['id'] == situation_id]
        self.week()

    def test_twelve_situations_with_parsable_advice_and_sane_chances(self):
        self.all_groups()
        situations = load_config(ROOT / 'data/world/semantic.json')['situations']
        self.assertGreaterEqual(len(situations), 10)
        for spec in situations:
            card = self.card(spec['advice'])
            self.assertEqual(card.topic, spec['topic'], spec['advice'])
            self.assertIn(card.target_id, spec['groups'], spec['advice'])
            chance = self.runtime.evaluate(self.state, card)[0].chance
            self.assertTrue(15 <= chance <= 90, (spec['advice'], chance))
            self.say('отменить карточку')

    def test_situation_publishes_and_boosts_matching_topic(self):
        before = self.runtime.evaluate(self.state, self.card('встретиться с рабочими о зарплатах'))[0]
        self.say('отменить карточку')
        self.force('wage_delay')
        self.assertEqual(len([c for c in self.state.clippings if c['source'] == 'semantic_situation']), 1)
        self.assertIn('Задержка зарплат', self.say('ситуации'))
        after = self.runtime.evaluate(self.state, self.card('встретиться с рабочими о зарплатах'))[0]
        self.assertIn('situation', [r.source for r in after.reasons])
        self.assertAlmostEqual(after.effect, round(before.effect * 1.15, 3), places=2)
        self.assertEqual(after.chance, before.chance)

    def test_strike_situation_opens_event(self):
        self.force('plant_strike')
        hot = self.state.world['hot_groups']['workers']
        self.assertEqual(hot['event'], 'забастовка')
        self.assertGreaterEqual(hot['until'], self.state.week)

    def test_calm_city_has_no_situation(self):
        self.week()
        self.assertIn('спокойно', self.say('ситуации'))

    def test_passivity_costs_mood_and_one_article(self):
        self.runtime.config['passivity']['grace_weeks'] = 2
        mood = self.groups[0].mood
        for _ in range(4):
            self.week()
        self.assertEqual(self.groups[0].mood, mood - 2)
        self.assertEqual(len([c for c in self.state.clippings if c['source'] == 'semantic_passive']), 1)
        self.accept()
        self.week()
        self.assertEqual(self.state.world['semantic_passive_weeks'], 0)

    def test_rival_exploits_public_red_line(self):
        self.state.candidates.append(NS(id='lozhkin', name='Ложкин'))
        self.accept('встретиться с рабочими за сокращения')
        mood = self.groups[0].mood
        self.week(0)
        rival = [c for c in self.state.clippings if c['source'] == 'semantic_rival']
        self.assertEqual(len(rival), 1)
        self.assertIn('пользуется ошибкой', rival[0]['lead'])
        self.assertLess(self.groups[0].mood, mood)

    def test_rival_argues_with_opposite_stance(self):
        self.state.candidates.append(NS(id='voronina', name='Воронина'))
        self.accept('встретиться с рабочими против сокращений')
        self.week()
        rival = [c for c in self.state.clippings if c['source'] == 'semantic_rival']
        self.assertEqual(len(rival), 1)
        self.assertIn('Воронина', rival[0]['headline'])

    def test_advisor_and_tutorial(self):
        self.force('tax_raids')
        text = self.say('советник')
        self.assertIn('вне игрового мира', text)
        self.assertIn('встретиться с предпринимателями о налогах', text)
        self.assertIn('Хуже всего', text)
        self.assertIn('Обучение', self.say('обучение'))
        self.assertFalse(self.legacy_calls)


del contract

if __name__ == '__main__':
    unittest.main()
