"""Dossier/red-line/press integration on the actual engine; run in repository CI."""
import copy
import json
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
from dossiers import DossierRuntime


class LiveDossierTests(unittest.TestCase):
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
        self.runtime = DossierRuntime.from_file(main, ROOT / 'data/world/semantic.json')
        self.runtime.install()
        self.state, self.rng = main.new_game(data, 777, 'Смысловой тест', 35)
        self.state.player.money = 5000
        self.assertEqual(self.state.next_election_week, 24)
        for group in self.state.groups:
            group.mood = 70  # no unrelated pressure event can mask this test
        main.save_game(self.state, self.rng)
        self.path = self.store._path(self.session.slot_id)
        self.initial = self.path.read_bytes()
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

    def test_dossier_red_line_and_press_on_real_engine(self):
        self.assertIn('Красная линия', self.say('досье рабочие')['message'])
        qa = self.accepted('встретиться с рабочими за сокращения')
        self.assertLess(qa['semantic_audience']['workers'], 0)
        self.assertIn('red_line', [r['source'] for r in qa['semantic_evaluation']['reasons']])
        self.complete()
        self.assertTrue(any(c.get('source') == 'semantic_press' for c in self.state.clippings))


if __name__ == '__main__':
    unittest.main()
