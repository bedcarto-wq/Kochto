"""Small hand-written Russian regression set, not the full acceptance corpus."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from semantic_parser import parse_action

GRAMMAR = json.loads((Path(__file__).parent / 'fixtures' / 'semantic_grammar.json').read_text(encoding='utf-8'))
ENTITIES = {
    'group': {'workers': ['рабочими', 'рабочим'], 'teachers': ['учителями', 'учителям']},
    'npc': {'mayor_old': ['мэра', 'мэру']},
    'rival': {'lozhkin': ['Ложкина']},
    'publication': {'independent': ['Кочто сегодня']},
}
TOPICS = {'jobs': ['сокращениях', 'сокращения', 'сокращений', 'работе'],
          'education': ['школе'], 'healthcare': ['медицине']}


def parse(text, grammar=GRAMMAR):
    return parse_action(text, grammar, ENTITIES, TOPICS)


class ParserTests(unittest.TestCase):
    def test_short_meeting(self):
        result = parse('Встретиться с рабочими')
        self.assertEqual('parsed', result.status)
        self.assertEqual('workers', result.card.target_id)
        self.assertEqual('', result.card.topic)
        self.assertFalse(result.card.confirmed)

    def test_detailed_meeting_preserves_meaning(self):
        text = 'Публично встретиться с рабочими у проходной и обсудить сокращения'
        result = parse(text)
        self.assertEqual('parsed', result.status)
        c = result.card
        self.assertEqual(('meeting', 'workers', 'jobs', 'factory_gate', 'public'),
                         (c.action_type, c.target_id, c.topic, c.place, c.visibility))
        self.assertEqual(text, c.raw)
        for ev in c.evidence:
            self.assertTrue(text[ev.start:ev.end].strip())
            self.assertTrue(ev.linked)

    def test_topic_does_not_replace_target(self):
        c = parse('Встретиться с рабочими о школе').card
        self.assertEqual(('workers', 'education'), (c.target_id, c.topic))

    def test_negative_action_cancelled(self):
        for text in ('Не встретиться с рабочими', 'Не буду встретиться с рабочими',
                     'Отказываюсь встретиться с рабочими', 'Тайно не подкупить мэра'):
            with self.subTest(text=text):
                self.assertEqual('cancelled', parse(text).status)

    def test_against_topic_is_not_refusal(self):
        result = parse('Встретиться с рабочими против сокращений')
        self.assertEqual('parsed', result.status)
        self.assertEqual(('jobs', 'against'), (result.card.topic, result.card.stance))

    def test_without_money_is_not_refusal(self):
        self.assertEqual('parsed', parse('Встретиться с рабочими без денег').status)

    def test_noun_salad_rejected(self):
        for text in ('рабочие деньги тайно школа', 'встреча рабочие сокращения', 'мэр газета рынок'):
            with self.subTest(text=text):
                self.assertEqual('unsupported', parse(text).status)

    def test_missing_target_asks(self):
        self.assertEqual('needs_choice', parse('Встретиться о работе').status)

    def test_two_targets_not_silently_lost(self):
        self.assertEqual('needs_choice', parse('Встретиться с рабочими и учителями').status)

    def test_two_actions_ask_for_split(self):
        self.assertEqual('needs_choice', parse('Встретиться с рабочими и подкупить мэра').status)

    def test_topic_requires_relation(self):
        c = parse('Встретиться с рабочими школа медицина').card
        self.assertEqual('', c.topic)
        self.assertFalse(any(ev.field == 'topic' for ev in c.evidence))

    def test_two_topics_ask(self):
        self.assertEqual('needs_choice', parse('Встретиться с рабочими о школе и о работе').status)

    def test_explicit_money_not_random_number(self):
        self.assertEqual({'money': 200}, parse('Организовать субботник с рабочими выделить 200 рублей').card.resources)
        self.assertEqual({}, parse('Встретиться с рабочими на 24 неделе').card.resources)

    def test_multiple_amounts_ask(self):
        self.assertEqual('needs_choice', parse('Организовать субботник выделить 200 рублей потратить 300 рублей').status)

    def test_goal_retained(self):
        c = parse('Встретиться с рабочими чтобы узнать их требования').card
        self.assertEqual('узнать их требования', c.goal)

    def test_literal_alias_not_regex(self):
        entities = {'group': {'literal': ['[рабочими]']}}
        result = parse_action('Встретиться с рабочими', GRAMMAR, entities, TOPICS)
        self.assertEqual('needs_choice', result.status)

    def test_case_and_whitespace(self):
        c = parse('  ВСТРЕТИТЬСЯ   с   рабочими о работе ').card
        self.assertEqual(('workers', 'jobs'), (c.target_id, c.topic))

    def test_outside_world_honest_boundaries(self):
        result = parse('Телепортироваться в столицу')
        self.assertEqual('unsupported', result.status)
        self.assertTrue(0 < len(result.suggestions) <= 3)

    def test_never_auto_confirms_or_rewards(self):
        c = parse('Публично встретиться с рабочими о работе').card
        self.assertFalse(c.confirmed)
        self.assertEqual(frozenset(), c.authored_fields())

    def test_inner_negation_not_ignored(self):
        for text in ('Встретиться с рабочими не о работе',
                     'Встретиться с рабочими и не подкупить мэра'):
            self.assertEqual('needs_choice', parse(text).status)

    def test_yo_alias_normalization_preserves_offsets(self):
        entities = {'group': {'youth': ['молодёжью']}}
        text = 'Встретиться с молодёжью'
        c = parse_action(text, GRAMMAR, entities, TOPICS).card
        self.assertEqual('youth', c.target_id)
        ev = next(ev for ev in c.evidence if ev.field == 'target')
        self.assertEqual('молодёжью', text[ev.start:ev.end])

    def test_parse_confirm_evaluate_composition(self):
        from dataclasses import replace
        from semantic_actions import ActionContext, evaluate_action
        rules = json.loads((Path(__file__).parent / 'fixtures' / 'semantic_rules.json').read_text())
        profile = {'issues': {'jobs': 75}}
        short = replace(parse('Встретиться с рабочими').card, confirmed=True)
        detailed = replace(parse('Публично встретиться с рабочими у проходной и обсудить сокращения').card, confirmed=True)
        short_result = evaluate_action(short, 50, 10, profile, rules, ActionContext())
        detail_result = evaluate_action(detailed, 50, 10, profile, rules, ActionContext(event_place_match=1.2))
        self.assertGreater(detail_result.chance, short_result.chance)
        self.assertGreater(detail_result.effect, short_result.effect)

    def test_interview_frame(self):
        result = parse('Дать интервью газете Кочто сегодня о медицине')
        self.assertEqual('parsed', result.status)
        self.assertEqual(('interview', 'independent', 'healthcare'),
                         (result.card.action_type, result.card.target_id, result.card.topic))


if __name__ == '__main__':
    unittest.main()
