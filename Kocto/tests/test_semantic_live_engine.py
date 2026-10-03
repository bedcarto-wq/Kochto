"""Integration tests against the actual engine; run in repository CI."""
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
from semantic_runtime import SemanticRuntime, PENDING, HISTORY


class LiveEngineTests(unittest.TestCase):
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
        self.runtime = SemanticRuntime.from_file(main, ROOT / 'data/world/semantic.json')
        self.runtime.install()
        self.state, self.rng = main.new_game(data, 777, 'Смысловой тест', 35)
        self.state.player.money = 5000
        for group in self.state.groups:
            group.mood = 70
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

    def test_meeting_full_week_and_checkpoint(self):
        money = self.state.player.money
        self.say('встретиться с рабочими о зарплатах')
        self.assertEqual(self.state.player.money, money)
        qa = self.state.parser_context[PENDING]['card']
        self.assertEqual(qa['topic'], 'wages')
        queued = self.accepted('встретиться с рабочими о зарплатах')
        self.assertEqual(self.path.read_bytes(), self.initial)
        self.assertEqual(queued['semantic_card']['target_id'], 'workers')
        self.assertIn('зарплатах', queued['semantic_card']['raw'])
        queued['semantic_evaluation']['chance'] = 100
        group = systems.get_group(self.state, 'workers')
        mood = group.mood
        review = systems.begin_week_end(self.state)
        self.assertEqual(group.mood, mood)
        self.assertIs(review, systems.begin_week_end(self.state))
        delta = next(effect['delta'] for effect in review[0]['script']['effects'] if effect['type'] == 'group_mood')
        systems.finish_week(self.state, [])
        self.assertEqual(group.mood, mood + delta)
        main._clear_pending(self.state)
        main.save_game(self.state, self.rng)
        self.assertEqual(self.store.load(self.session.slot_id)['week'], 2)
        self.assertEqual(self.store.load_backup(self.session.slot_id)['week'], 1)
        self.assertEqual(self.state.world[HISTORY][0]['card']['topic'], 'wages')
        loaded, rng, note = self.session.load_game()
        self.assertEqual(loaded.world[HISTORY], self.state.world[HISTORY])

    def test_interview_actual_engine_preserves_publication(self):
        qa = self.accepted('дать интервью газете Кочто сегодня о налогах')
        advertised = qa['chance']
        review = self.complete()
        self.assertEqual(review[0]['script']['semantic_card']['target_id'], 'independent')
        self.assertEqual(review[0]['script']['semantic_evaluation']['chance'], advertised)
        self.assertEqual(set(qa['semantic_audience']), {group.id for group in self.state.groups})
        self.assertEqual(review[0]['text']['publication'], 'independent')

    def test_volunteer_actual_engine_uses_organization_and_topic(self):
        qa = self.accepted('организовать субботник с врачами о медицине')
        self.assertEqual(qa['semantic_card']['action_type'], 'volunteer_work')
        self.assertEqual(qa['semantic_card']['target_id'], 'doctors')
        self.assertEqual(qa['cost_paid'], 150)
        review = self.complete()
        self.assertTrue(review[0]['executed'])
        self.assertEqual(review[0]['script']['semantic_card']['topic'], 'healthcare')

    def test_cancel_returns_actual_cost_and_does_not_record_execution(self):
        self.say('встретиться с рабочими о работе')
        self.say('карточка деньги 500')
        self.say('подтвердить действие')
        self.assertEqual(self.state.player.money, 4500)
        self.say('отменить 1')
        self.assertEqual(self.state.player.money, 5000)
        self.assertFalse(self.state.week_actions)
        self.complete()
        self.assertFalse(self.state.world[HISTORY])

    def test_repeat_penalty_survives_real_save_load(self):
        first = self.accepted('встретиться с рабочими о работе')['chance']
        self.complete()
        self.state, self.rng, _ = self.session.load_game()
        second = self.accepted('встретиться с рабочими о работе')['chance']
        self.assertLess(second, first)

    def test_negation_does_not_learn_or_spend(self):
        self.accepted('встретиться с рабочими о работе')
        old_memory = copy.deepcopy(self.memory)
        money = self.state.player.money
        self.assertIn('отменено', self.say('не встретиться с рабочими о работе')['message'])
        self.assertEqual(self.memory, old_memory)
        self.assertEqual(self.state.player.money, money)
        self.assertEqual(len(self.state.week_actions), 1)


if __name__ == '__main__':
    unittest.main()
