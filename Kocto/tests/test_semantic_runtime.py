"""Fast contract tests with a minimal injected engine, not a real playtest."""
import copy
import json
import random
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from semantic_runtime import SemanticRuntime, PENDING, KEY, HISTORY


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / 'data/world/semantic.json').read_text(encoding='utf-8'))
        self.groups = [NS(id='workers', name='Рабочие', issues={'jobs':75,'taxes':40}, mood=50),
                       NS(id='business', name='Предприниматели', issues={'taxes':80}, mood=50)]
        self.state = NS(week=1, world={}, parser_context={}, week_actions=[], actions_this_week=0,
                        is_game_over=False, groups=self.groups, candidates=[], npcs=[],
                        publications=[NS(id='independent', name='Кочто сегодня')],
                        player=NS(name='Тест', money=5000, charisma=5, media=5, organization=5),
                        next_archive_no=1, clippings=[], news_feed=[])
        self.legacy_calls = []
        self.logs = []
        self.pending = []
        self.saved_memory = []
        sysmod = NS(DATA=NS(dictionaries={}), ACTIONS={
                    'meet_group':NS(id='meet_group', intent='meet', cost=100),
                    'article':NS(id='article', intent='media', cost=200)},
                    get_group=lambda state, key: next((g for g in state.groups if g.id == key), None),
                    add_log=lambda state, message: self.logs.append(message),
                    enqueue_action=self.enqueue, _effective_action=lambda state, qa: copy.copy(sysmod.ACTIONS[qa['action_id']]),
                    resolve_action=lambda *args: self.fail('semantic resolution fell back to legacy'),
                    begin_week_end=self.begin, finish_week=self.finish,
                    plan_lines=lambda state: ['legacy'] * len(state.week_actions))
        self.engine = NS(systems=sysmod, handle_command=lambda *args: self.legacy_calls.append(args[2]) or {'message':'legacy'},
                         _clear_pending=lambda state: None, save_game=lambda *args: None,
                         save_memory=lambda value: self.saved_memory.append(copy.deepcopy(value)))
        self.runtime = SemanticRuntime(self.engine, self.config)
        self.runtime.install()
        self.memory = {}
        self.rng = random.Random(2)

    def tearDown(self):
        self.runtime.uninstall()

    def say(self, text):
        return self.engine.handle_command(self.state, self.rng, text, self.memory)['message']

    def enqueue(self, state, action, target, intent, delayed, issue, meta):
        if len(state.week_actions) >= 3:
            return False, 'Нет слотов недели.'
        state.player.money -= action.cost
        state.week_actions.append(dict(action_id=action.id, target=target, intent=intent,
                                       issue=issue, raw=meta['raw'], cost_paid=action.cost, chance=1))
        state.actions_this_week += 1
        return True, 'legacy accepted'

    def begin(self, state):
        self.pending = []
        for index, qa in enumerate(state.week_actions):
            action = self.engine.systems._effective_action(state, qa)
            executed, success, text, script, clipping = self.engine.systems.resolve_action(state, action, self.rng)
            self.pending.append({'index':index, 'script':script, 'success':success})
        return self.pending

    def finish(self, state, verdicts, rng_unused=None):
        for item in self.pending:
            for effect in item['script']['effects']:
                if effect['type'] == 'group_mood':
                    self.engine.systems.get_group(state, effect['group']).mood += effect['delta']
        state.week += 1
        state.week_actions = []
        state.actions_this_week = 0

    def accept(self, phrase='встретиться с рабочими о работе'):
        self.assertIn('Понял как', self.say(phrase))
        self.assertIn('Принято после подтверждения', self.say('подтвердить действие'))
        return self.state.week_actions[-1]

    def test_draft_does_not_spend_or_learn(self):
        self.say('встретиться с рабочими о работе')
        self.assertEqual(self.state.player.money, 5000)
        self.assertFalse(self.state.week_actions)
        self.assertFalse(self.runtime.cache(self.memory))

    def test_confirmation_once_preserves_card(self):
        qa = self.accept()
        self.assertTrue(qa['semantic_card']['confirmed'])
        self.assertEqual(qa['semantic_card']['topic'], 'jobs')
        self.assertEqual(self.state.player.money, 4900)
        self.assertIn('Нет действия', self.say('подтвердить действие'))
        self.assertEqual(len(self.state.week_actions), 1)
        self.assertTrue(self.saved_memory)

    def test_cancel_is_free(self):
        self.say('встретиться с рабочими о работе')
        self.say('отменить карточку')
        self.assertNotIn(PENDING, self.state.parser_context)
        self.assertEqual(self.state.player.money, 5000)

    def test_unknown_and_dirty_do_not_fall_back(self):
        for phrase in ('лететь на луну', 'подкупить рабочих', 'незаконно встретиться с рабочими о работе'):
            self.say(phrase)
            self.assertFalse(self.state.week_actions)
            self.assertNotIn(PENDING, self.state.parser_context)
        self.assertFalse(self.legacy_calls)

    def test_negation_never_recalls_positive(self):
        self.accept()
        self.assertIn('отменено', self.say('не встретиться с рабочими о работе'))
        self.assertNotIn(PENDING, self.state.parser_context)
        self.assertEqual(len(self.state.week_actions), 1)

    def test_edit_and_invalid_edit_are_atomic(self):
        self.say('встретиться с рабочими о работе')
        self.say('карточка тема taxes')
        self.assertEqual(self.state.parser_context[PENDING]['card']['topic'], 'taxes')
        previous = copy.deepcopy(self.state.parser_context[PENDING])
        self.say('карточка тема неизвестно')
        self.assertEqual(previous, self.state.parser_context[PENDING])

    def test_explicit_money_keeps_nonzero_effects(self):
        self.say('встретиться с рабочими о работе')
        self.say('карточка деньги 500')
        self.say('подтвердить действие')
        qa = self.state.week_actions[-1]
        self.assertEqual(qa['cost_paid'], 500)
        self.assertGreater(qa['semantic_audience']['workers'], 0)
        self.assertEqual(self.state.player.money, 4500)

    def test_cannot_afford_keeps_draft(self):
        self.say('встретиться с рабочими о работе')
        self.state.player.money = 50
        self.assertIn('Недостаточно', self.say('подтвердить действие'))
        self.assertIn(PENDING, self.state.parser_context)
        self.assertFalse(self.state.week_actions)

    def test_stale_week_rejects_confirmation(self):
        self.say('встретиться с рабочими о работе')
        self.state.week += 1
        self.assertIn('изменился', self.say('подтвердить действие'))
        self.assertFalse(self.state.week_actions)

    def test_dictionary_change_invalidates_draft_and_cache(self):
        self.accept()
        self.say('встретиться с рабочими о работе')
        self.engine.systems.DATA.dictionaries = {'version':2}
        self.assertIn('изменился', self.say('подтвердить действие'))
        self.assertFalse(self.runtime.cache(self.memory))

    def test_repetition_reduces_preview(self):
        first = self.accept()['chance']
        second = self.accept()['chance']
        self.assertLess(second, first)

    def test_effects_applied_once_and_review_does_not_reroll(self):
        qa = self.accept()
        qa['semantic_evaluation']['chance'] = 100
        before = self.groups[0].mood
        review = self.engine.systems.begin_week_end(self.state)
        self.assertEqual(self.groups[0].mood, before)
        self.assertIs(review, self.engine.systems.begin_week_end(self.state))
        delta = sum(e['delta'] for e in review[0]['script']['effects'] if e['type'] == 'group_mood')
        self.engine.systems.finish_week(self.state, [])
        self.assertEqual(self.groups[0].mood, before + delta)
        self.assertEqual(len(self.state.world[HISTORY]), 1)
        with self.assertRaises(RuntimeError):
            self.engine.systems.finish_week(self.state, [])

    def test_actual_roll_uses_advertised_chance(self):
        qa = self.accept()
        qa['semantic_evaluation']['chance'] = 0
        review = self.engine.systems.begin_week_end(self.state)
        self.assertFalse(review[0]['success'])
        self.assertIn('шанс 0%', review[0]['script']['primary'])

    def test_position_changes_group_effect_sign(self):
        self.say('встретиться с предпринимателями за налоги')
        self.say('подтвердить действие')
        self.assertLess(self.state.week_actions[-1]['semantic_audience']['business'], 0)

    def test_interview_preserves_publication_and_audiences(self):
        qa = self.accept('дать интервью газете Кочто сегодня о налогах')
        self.assertEqual(qa['semantic_card']['target_kind'], 'publication')
        self.assertEqual(qa['semantic_card']['target_id'], 'independent')
        self.assertEqual(set(qa['semantic_audience']), {'workers','business'})

    def test_new_failed_phrase_cannot_confirm_old_draft(self):
        self.say('встретиться с рабочими о работе')
        self.say('бессмыслица')
        self.assertIn('Нет действия', self.say('подтвердить действие'))

    def test_manual_goal_has_explicit_player_evidence(self):
        self.say('встретиться с рабочими о работе')
        self.say('карточка цель получить поддержку')
        card = self.state.parser_context[PENDING]['card']
        ev = next(e for e in card['evidence'] if e['field'] == 'goal')
        self.assertEqual(card['raw'][ev['start']:ev['end']], 'получить поддержку')

    def test_nonexistent_event_does_not_create_bonus(self):
        self.say('встретиться с рабочими о работе на забастовке')
        self.assertNotIn(PENDING, self.state.parser_context)
        self.state.world['hot_groups'] = {'workers':{'event':'забастовка','until':3}}
        self.assertIn('Понял как', self.say('встретиться с рабочими о работе на забастовке'))

    def test_layoffs_not_conflated_with_jobs(self):
        qa = self.accept('встретиться с рабочими против сокращений')
        self.assertEqual(qa['semantic_card']['topic'], 'layoffs')
        self.assertGreater(qa['semantic_audience']['workers'], 0)

    def test_service_commands_remain_available(self):
        self.assertEqual(self.say('город'), 'legacy')
        self.assertEqual(self.legacy_calls, ['город'])


if __name__ == '__main__':
    unittest.main()
