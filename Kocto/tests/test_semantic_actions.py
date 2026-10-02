"""Unit tests for the new isolated core; NOT a natural-language benchmark."""
from __future__ import annotations

import itertools
import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from semantic_actions import (ACTION_TYPES, ActionCard, ActionContext, CardError,
                              ConfirmedCardMemory, Evidence, evaluate_action)

RULES = json.loads((Path(__file__).parent / 'fixtures' / 'semantic_rules.json').read_text(encoding='utf-8'))
PROFILE = {'issues': {'jobs': 75, 'education': 10},
           'channels': {'personal': 1, 'newspaper': 0.2},
           'positions': {'jobs': 'for'}}


def card(**changes):
    args = dict(action_type='meeting', raw='Встретиться с рабочими',
                target_kind='group', target_id='workers', confirmed=True)
    args.update(changes)
    return ActionCard(**args)


def evaluate(c=None, ctx=None, rules=None, profile=None):
    return evaluate_action(c or card(), 50, 10,
                           PROFILE if profile is None else profile,
                           RULES if rules is None else rules,
                           ctx or ActionContext())


class CardTests(unittest.TestCase):
    def test_25_types(self):
        self.assertEqual(25, len(ACTION_TYPES))
        for action_type in ACTION_TYPES:
            self.assertEqual(action_type, card(action_type=action_type).action_type)

    def test_json_roundtrip(self):
        c = card(topic='jobs', facts=('factory_debt',), resources={'money': 200},
                 evidence=(Evidence('target', 14, 21, linked=True),))
        self.assertEqual(c.to_dict(), ActionCard.from_dict(json.loads(json.dumps(c.to_dict()))).to_dict())

    def test_unknown_values_rejected(self):
        for name, value in [('action_type', 'teleport'), ('target_kind', 'dragon'),
                            ('stance', 'maybe'), ('visibility', 'sometimes'),
                            ('channel', 'magic'), ('legality', 'whatever')]:
            with self.subTest(name=name), self.assertRaises(CardError):
                card(**{name: value})

    def test_invalid_resources(self):
        for resources in ({'money': -1}, {'money': float('nan')},
                          {'money': float('inf')}, {'money': True},
                          {'money': '200'}, {'magic': 1}):
            with self.subTest(resources=resources), self.assertRaises(CardError):
                card(resources=resources)

    def test_incomplete_target(self):
        with self.assertRaises(CardError):
            card(target_id='')

    def test_stance_needs_topic(self):
        with self.assertRaises(CardError):
            card(stance='against')

    def test_evidence_bounds(self):
        for ev in (Evidence('goal', -1, 2), Evidence('goal', 0, 100),
                   Evidence('goal', 2, 2), Evidence('nonsense', 0, 2)):
            with self.subTest(ev=ev), self.assertRaises(CardError):
                card(evidence=(ev,))

    def test_unknown_version(self):
        for version in (2, True):
            with self.assertRaises(CardError):
                card(schema_version=version)

    def test_no_length_bonus(self):
        a = evaluate(card(raw='Встретиться с рабочими'))
        b = evaluate(card(raw='Встретиться с рабочими ' + 'важно очень ' * 100))
        self.assertEqual((a.chance, a.effect), (b.chance, b.effect))
        self.assertEqual(0, b.creativity_chance)

    def test_signature_ignores_wording(self):
        self.assertEqual(card().signature(), card(raw='Провести встречу с рабочими').signature())

    def test_signature_changes_with_content(self):
        self.assertNotEqual(card(topic='jobs').signature(), card(topic='education').signature())

    def test_input_resources_copied(self):
        resources = {'money': 200}
        c = card(resources=resources)
        resources['money'] = 999
        self.assertEqual(200, c.resources['money'])


class EvaluationTests(unittest.TestCase):
    def test_confirmation_required(self):
        with self.assertRaises(CardError):
            evaluate(card(confirmed=False))

    def test_topic_changes_result(self):
        self.assertGreater(evaluate(card(topic='jobs')).effect,
                           evaluate(card(topic='education')).effect)

    def test_unknown_topic_neutral(self):
        self.assertEqual(evaluate().effect, evaluate(card(topic='unknown')).effect)

    def test_wrong_channel_reduces_reach(self):
        self.assertGreater(evaluate(card(channel='personal')).effect,
                           evaluate(card(channel='newspaper')).effect)

    def test_position_changes_signed_effect(self):
        positive = evaluate(card(topic='jobs', stance='for'))
        negative = evaluate(card(topic='jobs', stance='against'))
        self.assertEqual(positive.chance, negative.chance)
        self.assertEqual(positive.effect, -negative.effect)

    def test_place_event_and_goal_resolved_context(self):
        base = evaluate()
        for c in (ActionContext(event_place_match=1.2),
                  ActionContext(method_goal_match=1.2)):
            self.assertGreater(evaluate(ctx=c).chance, base.chance)
            self.assertGreater(evaluate(ctx=c).effect, base.effect)

    def test_resources_cap_scale(self):
        result = evaluate(card(resources={'money': 1000}),
                          ActionContext(available_resources={'money': 200}))
        self.assertEqual(2, result.effect)

    def test_multiple_resource_bottleneck(self):
        c = card(resources={'money': 1000, 'people': 20})
        result = evaluate(c, ActionContext(available_resources={'money': 500, 'people': 2}))
        self.assertEqual(1, result.effect)

    def test_zero_resources_is_impossible(self):
        result = evaluate(card(resources={'money': 200}))
        self.assertEqual((0, 0), (result.chance, result.effect))

    def test_zero_channel_not_rescued_by_creativity(self):
        c = card(channel='newspaper', evidence=(Evidence('channel', 0, 5, linked=True),))
        result = evaluate(c, profile={'channels': {'newspaper': 0}})
        self.assertGreater(result.creativity_chance, 0)
        self.assertEqual((0, 0), (result.chance, result.effect))

    def test_repetition_and_consistency_reduce_effect(self):
        self.assertGreater(evaluate().effect, evaluate(ctx=ActionContext(repetitions=2)).effect)
        self.assertGreater(evaluate().effect, evaluate(ctx=ActionContext(consistency=0.5)).effect)

    def test_keywords_not_linked_no_creativity(self):
        c = card(topic='jobs', channel='personal', goal='выиграть',
                 evidence=(Evidence('topic', 0, 5, linked=False),))
        self.assertEqual(0, evaluate(c).creativity_chance)

    def test_assistant_does_not_earn_inventiveness(self):
        c = card(topic='jobs', evidence=(Evidence('topic', 0, 5, source='assistant', linked=True),))
        self.assertEqual(0, evaluate(c).creativity_chance)

    def test_absent_fields_do_not_earn_bonus(self):
        c = card(evidence=(Evidence('goal', 0, 5, linked=True),))
        self.assertEqual(0, evaluate(c).creativity_chance)

    def test_only_known_facts_rewarded(self):
        c = card(facts=('mayor_debt',), evidence=(Evidence('facts', 0, 5, linked=True),))
        unknown = evaluate(c)
        known = evaluate(c, ActionContext(known_facts=frozenset({'mayor_debt'})))
        self.assertGreater(known.creativity_chance, unknown.creativity_chance)

    def test_all_factors_have_reasons(self):
        sources = {r.source for r in evaluate().reasons}
        self.assertEqual({'topic_target', 'channel_target', 'place_time', 'method_goal',
                          'resources_scale', 'consistency', 'repetition', 'creativity'}, sources)

    def test_bonus_caps(self):
        c = card(facts=tuple(f'fact{i}' for i in range(100)),
                 evidence=(Evidence('facts', 0, 5, linked=True),))
        result = evaluate(c, ActionContext(known_facts=frozenset(c.facts), has_linked_chain=True))
        self.assertLessEqual(result.creativity_chance, 20)
        self.assertLessEqual(result.creativity_effect, 1.5)

    def test_missing_or_invalid_rules_fail_explicitly(self):
        for rules in ({}, dict(RULES, repeat_decay=2), dict(RULES, max_creativity_effect=2)):
            with self.assertRaises(CardError):
                evaluate(rules=rules)

    def test_nonfinite_base_and_context(self):
        with self.assertRaises(CardError):
            evaluate_action(card(), float('nan'), 10, PROFILE, RULES, ActionContext())
        with self.assertRaises(CardError):
            evaluate(ctx=ActionContext(method_goal_match=float('inf')))

    def test_300_structured_combinations_deterministic(self):
        # 25 types * 3 topics * 2 channels * 2 repetition levels = 300.
        # These are structured fixtures, NOT 300 parsed Russian phrases.
        combos = list(itertools.product(sorted(ACTION_TYPES), ('', 'jobs', 'education'),
                                        ('personal', 'newspaper'), (0, 2)))
        self.assertEqual(300, len(combos))
        for action_type, topic, channel, repeats in combos:
            c = card(action_type=action_type, topic=topic, channel=channel)
            ctx = ActionContext(repetitions=repeats)
            a = evaluate(c, ctx)
            self.assertEqual(a, evaluate(c, ctx))
            self.assertTrue(0 <= a.chance <= 90)


class MemoryTests(unittest.TestCase):
    def test_unconfirmed_not_learned(self):
        with self.assertRaises(CardError):
            ConfirmedCardMemory('v1').remember(card(confirmed=False))

    def test_remember_forget(self):
        memory = ConfirmedCardMemory('v1')
        memory.remember(card())
        self.assertIsNotNone(memory.recall('  ВСТРЕТИТЬСЯ   с рабочими '))
        memory.forget(card().raw)
        self.assertIsNone(memory.recall(card().raw))

    def test_negation_never_stripped(self):
        memory = ConfirmedCardMemory('v1')
        memory.remember(card())
        self.assertIsNone(memory.recall('Не встретиться с рабочими'))

    def test_dictionary_update_invalidates_memory(self):
        memory = ConfirmedCardMemory('v1')
        memory.remember(card())
        memory.use_dictionary('v1')
        self.assertIsNotNone(memory.recall(card().raw))
        memory.use_dictionary('v2')
        self.assertIsNone(memory.recall(card().raw))

    def test_recalled_card_is_independent(self):
        memory = ConfirmedCardMemory('v1')
        memory.remember(card(resources={'money': 200}))
        memory.recall(card().raw).resources['money'] = 999
        self.assertEqual(200, memory.recall(card().raw).resources['money'])


if __name__ == '__main__':
    unittest.main()
