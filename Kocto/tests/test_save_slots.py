import copy
import json
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from save_slots import SaveError, SaveStore
from campaign_launcher import CampaignSession, select_console


def game(name='Алла', week=1, **extra):
    return dict({'_schema': 'kochto.proto.1', 'seed': 17, 'week': week,
                 'player': {'name': name, 'role': 'candidate', 'money': 100},
                 'rng_state': '', 'is_game_over': False, 'game_over_reason': ''}, **extra)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = SaveStore(Path(self.temp.name) / 'campaigns')

    def tearDown(self):
        self.temp.cleanup()

    def test_create_and_load(self):
        raw = game()
        slot = self.store.create(raw)
        self.assertEqual(raw, self.store.load(slot))
        info = self.store.list_slots()[0]
        self.assertEqual(('Алла', 1, 'candidate', 'alive'), (info.name, info.week, info.role, info.status))

    def test_names_are_not_paths(self):
        name = '../Алла?:<>|/\\*'
        slot = self.store.create(game(name))
        self.assertEqual(name, self.store.list_slots()[0].name)
        self.assertEqual(slot + '.json', next(self.store.root.glob('*.json')).name)

    def test_duplicate_names_preserve_both(self):
        a = self.store.create(game())
        b = self.store.create(game())
        self.assertNotEqual(a, b)
        self.assertEqual({'Алла', 'Алла (2)'}, {i.name for i in self.store.list_slots()})
        self.assertEqual('Алла', self.store.load(b)['player']['name'])

    def test_never_overwrite_existing_slot_on_create(self):
        slot = self.store.create(game())
        with self.assertRaises(SaveError):
            self.store.create(game('Другой'), slot)
        self.assertEqual('Алла', self.store.load(slot)['player']['name'])

    def test_backup_is_previous_checkpoint(self):
        slot = self.store.create(game())
        self.store.save(slot, game(week=2))
        self.store.save(slot, game(week=3))
        self.assertEqual(3, self.store.load(slot)['week'])
        self.assertEqual(2, self.store.load_backup(slot)['week'])
        self.assertEqual(1, len(self.store.list_slots()))

    def test_same_or_earlier_week_rejected(self):
        slot = self.store.create(game(week=2))
        for week in (1, 2):
            with self.assertRaises(SaveError):
                self.store.save(slot, game(week=week))

    def test_corruption_recovery_is_explicit(self):
        slot = self.store.create(game())
        self.store.save(slot, game(week=2))
        self.store._path(slot).write_text('{bad', encoding='utf-8')
        info = self.store.list_slots()[0]
        self.assertEqual('broken', info.status)
        self.assertTrue(info.has_backup)
        with self.assertRaises(SaveError):
            self.store.load(slot)
        self.store.restore(slot)
        self.assertEqual(1, self.store.load(slot)['week'])
        self.assertEqual(1, self.store.load_backup(slot)['week'])

    def test_corruption_does_not_replace_valid_backup(self):
        slot = self.store.create(game())
        self.store.save(slot, game(week=2))
        backup = self.store._path(slot, True).read_bytes()
        self.store._path(slot).write_text('{bad', encoding='utf-8')
        with self.assertRaises(SaveError):
            self.store.save(slot, game(week=3))
        self.assertEqual(backup, self.store._path(slot, True).read_bytes())

    def test_failed_atomic_replace_preserves_current(self):
        slot = self.store.create(game())
        original = os.replace
        def failing(source, dest):
            if Path(dest) == self.store._path(slot):
                raise OSError('simulated write failure')
            return original(source, dest)
        with patch('save_slots.os.replace', side_effect=failing):
            with self.assertRaises(OSError):
                self.store.save(slot, game(week=2))
        self.assertEqual(1, self.store.load(slot)['week'])
        self.assertEqual([], list(self.store.root.glob('*.tmp')))

    def test_delete_requires_confirmation(self):
        slot = self.store.create(game())
        with self.assertRaises(SaveError):
            self.store.delete(slot)
        self.assertTrue(self.store._path(slot).exists())

    def test_delete_cleans_slot_backup_and_memory(self):
        slot = self.store.create(game())
        self.store.save(slot, game(week=2))
        (self.store.root / (slot + '.memory.json')).write_text('{}')
        self.store.delete(slot, confirmed=True)
        self.assertEqual([], list(self.store.root.iterdir()))

    def test_dead_campaign_kept(self):
        slot = self.store.create(game(is_game_over=True, game_over_reason='death'))
        self.assertEqual('dead', self.store.list_slots()[0].status)
        self.assertTrue(self.store._path(slot).exists())

    def test_non_death_defeat_not_marked_dead(self):
        self.store.create(game(is_game_over=True, game_over_reason='election_loss'))
        self.assertEqual('alive', self.store.list_slots()[0].status)

    def test_wrong_format_marked_incompatible(self):
        slot = self.store.create(game())
        raw = json.loads(self.store._path(slot).read_text())
        raw['format'] = 'future.version'
        self.store._path(slot).write_text(json.dumps(raw))
        self.assertEqual('incompatible', self.store.list_slots()[0].status)

    def test_non_campaign_files_not_listed(self):
        self.store.root.mkdir(parents=True)
        (self.store.root / 'parser_memory.json').write_text('{}')
        (self.store.root / 'save.json').write_text('{}')
        self.assertEqual([], self.store.list_slots())

    def test_path_traversal_rejected(self):
        for slot in ('../../escape', '', 'save', 'A' * 32, True):
            with self.subTest(slot=slot), self.assertRaises(SaveError):
                self.store.load(slot)

    def test_bad_week_or_numbers_rejected(self):
        for week in (True, '2', -1, 0):
            with self.subTest(week=week), self.assertRaises(SaveError):
                self.store.create(game(week=week))
        with self.assertRaises(SaveError):
            self.store.create(game(bad=float('nan')))

    def test_slot_envelope_cannot_impersonate_another(self):
        slot = self.store.create(game())
        raw = json.loads(self.store._path(slot).read_text())
        raw['slot_id'] = '0' * 32
        self.store._path(slot).write_text(json.dumps(raw))
        with self.assertRaises(SaveError):
            self.store.load(slot)

    def test_input_and_loaded_data_are_independent(self):
        raw = game()
        slot = self.store.create(raw)
        raw['player']['money'] = 999
        loaded = self.store.load(slot)
        loaded['player']['money'] = 888
        self.assertEqual(100, self.store.load(slot)['player']['money'])

    def test_menu_delete_cancel_preserves_slot(self):
        slot = self.store.create(game())
        with patch('builtins.input', side_effect=['d 1', 'нет', 'q']), patch('builtins.print'):
            self.assertEqual(('quit', None), select_console(self.store))
        self.assertTrue(self.store._path(slot).exists())

    def test_menu_load_selected(self):
        slot = self.store.create(game())
        with patch('builtins.input', side_effect=['l 1']), patch('builtins.print'):
            self.assertEqual(('load', slot), select_console(self.store))

    def test_menu_eof_exits(self):
        with patch('builtins.input', side_effect=EOFError), patch('builtins.print'):
            self.assertEqual(('quit', None), select_console(self.store))

    def test_menu_dead_cannot_resume(self):
        self.store.create(game(is_game_over=True, game_over_reason='death'))
        with patch('builtins.input', side_effect=['l 1', 'q']), patch('builtins.print'):
            self.assertEqual(('quit', None), select_console(self.store))


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = SaveStore(Path(self.temp.name))
        # A minimal injected engine tests only the adapter contract locally.
        self.engine = SimpleNamespace(
            SCHEMA_TAG='kochto.proto.1',
            models=SimpleNamespace(game_to_dict=lambda state: copy.deepcopy(state.payload)),
            systems=SimpleNamespace(rng_state_to_json=lambda rng: repr(rng.getstate())),
            load_game=lambda: None, save_game=lambda *args: None,
            MEMORY_FILE=Path('old-memory'), SAVE_FILE=Path('old-save'))
        self.state = SimpleNamespace(week=1, week_actions=[], actions_this_week=0, rng_state='', payload=game())
        self.rng = random.Random(17)
        self.session = CampaignSession(self.engine, self.store, None)

    def tearDown(self):
        self.temp.cleanup()

    def test_first_checkpoint_saved(self):
        self.session.save_game(self.state, self.rng)
        self.assertEqual(1, self.store.load(self.session.slot_id)['week'])

    def test_midweek_and_close_do_not_save(self):
        self.session.save_game(self.state, self.rng)
        original = self.store._path(self.session.slot_id).read_bytes()
        self.state.week_actions = [{'id': 'meeting'}]
        self.state.actions_this_week = 1
        self.state.payload['player']['money'] = 75
        self.session.save_game(self.state, self.rng)
        self.assertEqual(original, self.store._path(self.session.slot_id).read_bytes())

    def test_completed_week_saved_with_backup(self):
        self.session.save_game(self.state, self.rng)
        self.state.week = 2
        self.state.payload['week'] = 2
        self.session.save_game(self.state, self.rng)
        self.assertEqual(2, self.store.load(self.session.slot_id)['week'])
        self.assertEqual(1, self.store.load_backup(self.session.slot_id)['week'])

    def test_uncompleted_advanced_state_not_saved(self):
        self.session.save_game(self.state, self.rng)
        self.state.week = 2
        self.state.payload['week'] = 2
        self.state.actions_this_week = 1
        self.session.save_game(self.state, self.rng)
        self.assertEqual(1, self.store.load(self.session.slot_id)['week'])

    def test_install_restore_and_isolated_memory(self):
        original_save = self.engine.save_game
        self.session.install()
        self.assertEqual(self.store.root / (self.session.slot_id + '.memory.json'), self.engine.MEMORY_FILE)
        with self.assertRaises(RuntimeError):
            self.session.install()
        self.session.uninstall()
        self.assertIs(original_save, self.engine.save_game)
        self.assertEqual(Path('old-memory'), self.engine.MEMORY_FILE)


if __name__ == '__main__':
    unittest.main()
