"""Story chains and the engine's evidence/investigation pipeline on the real engine (CI)."""
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
from campaign_chains import ChainRuntime, CHAINS


class LiveChainTests(unittest.TestCase):
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
        self.runtime = ChainRuntime.from_file(main, ROOT / 'data/world/semantic.json')
        self.runtime.config['situation_chance'] = 0
        self.runtime.install()
        self.state, self.rng = main.new_game(data, 777, 'Тест историй', 35)
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

    def test_promise_starts_union_chain_and_survives_save(self):
        self.assertIn('Понял как', self.say('пообещать рабочим бороться за зарплаты'))
        self.say('подтвердить действие')
        self.complete()
        active = [i['id'] for i in self.state.world[CHAINS]['active']]
        self.assertIn('union_promise', active)
        self.assertIn('Профсоюз', self.say('цепочки'))
        loaded, _, _ = self.session.load_game()
        self.assertIn('union_promise', [i['id'] for i in loaded.world[CHAINS]['active']])

    def test_investigation_pipeline_diagnostic(self):
        """Dirty deeds feed the engine's own evidence/investigation/prison logic."""
        player = self.state.player
        self.runtime.config['dirty']['weekly_discovery'] = 1.0
        rows = []
        for week in range(8):
            text = self.say('незаконно встретиться с рабочими о работе')
            if 'Понял как' in text:
                self.say('подтвердить действие')
            if self.state.is_game_over:
                break
            self.complete()
            rows.append((self.state.week, player.evidence, player.investigation, player.threat,
                         getattr(player.prison_status, 'value', player.prison_status)))
            if self.state.is_game_over:
                break
        print('\nINVESTIGATION-DIAG week/evidence/investigation/threat/status:', rows,
              'game_over:', self.state.is_game_over, getattr(self.state, 'game_over_reason', ''))
        self.assertTrue(rows)
        self.assertGreater(rows[-1][1] + rows[-1][2], 0)
        if not self.state.is_game_over:
            loaded, _, _ = self.session.load_game()
            self.assertEqual(loaded.player.evidence, player.evidence)


if __name__ == '__main__':
    unittest.main()
