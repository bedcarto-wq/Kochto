"""City situations, rivals and advisor on the actual engine; run in repository CI."""
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
from campaign_world import WorldRuntime


class LiveWorldTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.old_paths = {name:getattr(main, name) for name in ('SAVE_DIR','SAVE_FILE','MEMORY_FILE')}
        main.SAVE_DIR = self.directory / 'saves'
        data, _ = models.load_data(models.DATA_DIR, main.ACTIVE_SCENARIO)
        systems.init_data(data, self.directory / 'runtime')
        language.init_constructions(self.directory / 'runtime')
        main.nn_analyzer_set(data)
        self.store = SaveStore(main.SAVE_DIR / 'campaigns')
        self.session = CampaignSession(main, self.store, None)
        self.session.install()
        self.runtime = WorldRuntime.from_file(main, ROOT / 'data/world/semantic.json')
        self.runtime.install()
        self.state, self.rng = main.new_game(data, 777, 'Смысловой тест', 35)
        self.state.player.money = 5000
        self.assertEqual(self.state.next_election_week, 24)
        for group in self.state.groups:
            group.mood = 70  # no unrelated pressure event can mask this test
        main.save_game(self.state, self.rng)
        self.memory = {}

    def tearDown(self):
        self.runtime.uninstall()
        self.session.uninstall()
        for name, value in self.old_paths.items():
            setattr(main, name, value)
        self.temp.cleanup()

    def say(self, text):
        return main.handle_command(self.state, self.rng, text, self.memory)

    def accepted(self, text):
        self.assertIn('Понял как', self.say(text)['message'])
        self.assertIn('Принято после подтверждения', self.say('подтвердить действие')['message'])
        return self.state.week_actions[-1]

    def complete(self):
        review = systems.begin_week_end(self.state)
        systems.finish_week(self.state, [])
        main._clear_pending(self.state)
        main.save_game(self.state, self.rng)
        return review

    def test_world_layer_on_real_engine(self):
        self.assertIn('Обучение', self.say('обучение')['message'])
        self.assertIn('вне игрового мира', self.say('советник')['message'])
        self.runtime.config['situation_chance'] = 1
        self.runtime.config['situations'] = [s for s in self.runtime.config['situations'] if s['id'] == 'plant_strike']
        rivals = [c.id for c in self.state.candidates if c.id in self.runtime.config['rivals']]
        self.accepted('встретиться с рабочими за сокращения')
        self.complete()
        sources = [c.get('source') for c in self.state.clippings]
        self.assertIn('semantic_situation', sources)
        self.assertEqual(self.state.world['hot_groups']['workers']['event'], 'забастовка')
        self.assertIn('Забастовка', self.say('ситуации')['message'])
        if rivals:
            self.assertIn('semantic_rival', sources)
        for _ in range(4):
            self.complete()
        self.assertIn('semantic_passive', [c.get('source') for c in self.state.clippings])


if __name__ == '__main__':
    unittest.main()
