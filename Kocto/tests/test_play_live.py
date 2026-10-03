"""Tutorial, dirty actions and rival ratings on the actual engine; run in repository CI."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import language
import main
import models
import systems
from campaign_launcher import CampaignSession
from save_slots import SaveStore
from campaign_play import PlayRuntime, TRACES, TUTORIAL


class LivePlayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.old_paths = {name: getattr(main, name) for name in ('SAVE_DIR', 'SAVE_FILE', 'MEMORY_FILE')}
        main.SAVE_DIR = self.directory / 'saves'
        data, _ = models.load_data(models.DATA_DIR, main.ACTIVE_SCENARIO)
        systems.init_data(data, self.directory / 'runtime')
        language.init_constructions(self.directory / 'runtime')
        main.nn_analyzer_set(data)
        self.store = SaveStore(main.SAVE_DIR / 'campaigns')
        self.session = CampaignSession(main, self.store, None)
        self.session.install()
        self.runtime = PlayRuntime.from_file(main, ROOT / 'data/world/semantic.json')
        self.runtime.config['situation_chance'] = 0
        self.runtime.install()
        self.state, self.rng = main.new_game(data, 777, 'Тест игры', 35)
        self.state.player.money = 5000
        for group in self.state.groups:
            group.mood = 70
        main.save_game(self.state, self.rng)
        self.memory = {}

    def tearDown(self):
        self.runtime.uninstall()
        self.session.uninstall()
        for name, value in self.old_paths.items():
            setattr(main, name, value)
        self.temp.cleanup()

    def say(self, text):
        return main.handle_command(self.state, self.rng, text, self.memory)['message']

    def complete(self):
        systems.begin_week_end(self.state)
        systems.finish_week(self.state, [])
        main._clear_pending(self.state)
        main.save_game(self.state, self.rng)

    def test_tutorial_dirty_and_ratings_on_real_engine(self):
        self.assertTrue(self.state.world[TUTORIAL]['active'])
        self.assertIn('Обучение 2/7', self.say('досье рабочие'))
        self.assertIn('ГРЯЗНЫЙ МЕТОД', self.say('незаконно встретиться с рабочими о работе'))
        self.assertIn('Принято после подтверждения', self.say('подтвердить действие'))
        self.complete()
        self.assertEqual(self.state.world[TRACES][0]['status'], 'hidden')
        self.runtime.config['dirty'].update(weekly_discovery=10, max_discovery=1)
        evidence = self.state.player.evidence
        self.complete()
        self.assertIn('semantic_dirty', [c.get('source') for c in self.state.clippings])
        self.assertGreater(self.state.player.evidence, evidence)
        self.assertIn('Соперник', self.say('рейтинги'))


if __name__ == '__main__':
    unittest.main()
