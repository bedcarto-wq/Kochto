"""Integration with the real existing engine; executed by repository CI."""
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import language
import main
import models
import systems
from campaign_launcher import CampaignSession
from save_slots import SaveError, SaveStore


class RealEngineIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data, _ = models.load_data(models.DATA_DIR, main.ACTIVE_SCENARIO)
        systems.init_data(self.data, self.root / 'runtime')
        language.init_constructions(self.root / 'runtime')
        self.store = SaveStore(self.root / 'campaigns')
        self.session = CampaignSession(main, self.store, None)
        self.session.install()
        self.state, self.rng = main.new_game(self.data, 777, 'Тестовая кампания', 35)
        self.state.player.money = 5000
        main.save_game(self.state, self.rng)

    def tearDown(self):
        self.session.uninstall()
        self.temp.cleanup()

    def test_real_enqueue_not_saved_and_week_completion_is_saved(self):
        original = self.store._path(self.session.slot_id).read_bytes()
        result = main.handle_command(self.state, self.rng, 'встретиться с рабочими о зарплатах', {})
        self.assertIn('Принято', result['message'])
        self.assertTrue(self.state.week_actions)
        self.assertEqual(original, self.store._path(self.session.slot_id).read_bytes())
        systems.begin_week_end(self.state)
        systems.finish_week(self.state, [])
        main._clear_pending(self.state)
        main.save_game(self.state, self.rng)
        self.assertEqual(self.state.week, self.store.load(self.session.slot_id)['week'])
        self.assertEqual(1, self.store.load_backup(self.session.slot_id)['week'])

    def test_rng_and_full_state_roundtrip(self):
        selected = CampaignSession(main, self.store, self.session.slot_id)
        loaded, rng, _ = selected.load_game()
        expected = models.game_to_dict(self.state)
        self.assertEqual(expected, models.game_to_dict(loaded))
        self.assertEqual([self.rng.random() for _ in range(10)], [rng.random() for _ in range(10)])

    def test_death_kept_not_archived_or_loaded(self):
        self.state.week += 1
        self.state.current_week = self.state.week
        self.state.is_game_over = True
        self.state.game_over_reason = 'death'
        main.save_game(self.state, self.rng)
        self.assertEqual('dead', self.store.list_slots()[0].status)
        with self.assertRaises(SaveError):
            CampaignSession(main, self.store, self.session.slot_id).load_game()
        self.assertTrue(self.store._path(self.session.slot_id).exists())

    def test_defeat_campaign_continues(self):
        self.state.week += 1
        self.state.current_week = self.state.week
        self.state.is_game_over = True
        self.state.game_over_reason = 'election_loss'
        main.save_game(self.state, self.rng)
        loaded, _, note = CampaignSession(main, self.store, self.session.slot_id).load_game()
        self.assertFalse(loaded.is_game_over)
        self.assertTrue(note)


if __name__ == '__main__':
    unittest.main()
