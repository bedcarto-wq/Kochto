"""NPC/press story chains react to real deeds only (fake engine)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_play as contract
from campaign_chains import ChainRuntime, load_config, CHAINS
from campaign_play import TRACES

ROOT = Path(__file__).resolve().parents[1]


class ChainTests(contract.PlayTests):
    def setUp(self):
        super().setUp()
        self.runtime.uninstall()
        self.config = load_config(ROOT / 'data/world/semantic.json')
        self.config['situation_chance'] = 0
        self.config['passivity']['grace_weeks'] = 999
        self.config['dirty']['weekly_discovery'] = 0
        self.runtime = ChainRuntime(self.engine, self.config)
        self.runtime.install()

    def mood(self, gid):
        return next(g.mood for g in self.state.groups if g.id == gid)

    def chain(self, cid):
        return next((i for i in self.state.world.get(CHAINS, {}).get('active', []) if i['id'] == cid), None)

    def chain_news(self):
        return [c for c in self.state.clippings if c.get('source') == 'semantic_chain']

    def test_all_chain_advice_phrases_parse(self):
        self.all_groups()
        for spec in self.config['chains']:
            for step in spec['steps']:
                if step.get('advice'):
                    card = self.card(step['advice'])
                    self.assertTrue(self.runtime.matches(step['answer'], card.to_dict(), True,
                                                         {'topic': card.topic, 'target': card.target_id}), step['advice'])
                    self.say('отменить карточку')
        self.assertGreaterEqual(len(self.config['chains']), 5)

    def test_union_chain_two_steps_success(self):
        self.all_groups()
        self.accept('пообещать рабочим бороться за зарплаты')
        self.week()
        self.assertTrue(self.chain('union_promise')['announced'])
        self.assertIn('Мартынов', self.chain_news()[-1]['headline'])
        self.assertIn('Профсоюз', self.say('цепочки'))
        before = self.mood('workers')
        self.accept('встретиться с рабочими о зарплатах')
        self.week()
        self.assertEqual(self.chain('union_promise')['step'], 1)
        self.assertGreater(self.mood('workers'), before)
        self.week()  # announcement of step 2
        self.accept('собрать подписи среди рабочих против сокращений')
        self.week()
        self.assertIsNone(self.chain('union_promise'))
        self.assertEqual(self.state.world[CHAINS]['done']['union_promise']['result'], 'success')

    def test_ignoring_chain_fails_once_after_deadline(self):
        self.all_groups()
        self.accept('пообещать рабочим бороться за зарплаты')
        self.week()
        trust = self.state.player.trust
        for _ in range(6):
            self.week()
        done = self.state.world[CHAINS]['done']['union_promise']
        self.assertEqual(done['result'], 'fail')
        self.assertEqual(self.state.player.trust, max(0, trust - 3))

    def test_secret_or_offtopic_deed_does_not_answer(self):
        self.all_groups()
        self.accept('пообещать рабочим бороться за зарплаты')
        self.week()
        self.accept('тайно встретиться с рабочими о зарплатах')
        self.accept('встретиться с врачами о медицине')
        self.week()
        self.assertEqual(self.chain('union_promise')['step'], 0)

    def test_witness_blackmail_paid_buries_traces(self):
        self.all_groups()
        self.accept('незаконно встретиться с рабочими о работе')
        self.week()
        self.week()
        self.assertTrue(self.chain('witness')['announced'])
        money = self.state.player.money
        self.assertIn('Сделано', self.say('заплатить свидетелю'))
        self.assertEqual(self.state.player.money, money - 600)
        self.assertFalse([t for t in self.state.world[TRACES] if t['status'] == 'hidden'])
        self.assertEqual(self.state.player.evidence, 3)

    def test_witness_ignored_exposes(self):
        self.all_groups()
        self.accept('незаконно встретиться с рабочими о работе')
        for _ in range(6):
            self.week()
        self.assertEqual(self.state.world[CHAINS]['done']['witness']['result'], 'fail')
        self.assertTrue([t for t in self.state.world[TRACES] if t['status'] == 'exposed'])
        # the scandal itself opens the press follow-up chain
        self.assertIn('scandal_probe', [i['id'] for i in self.state.world[CHAINS]['active']]
                      + list(self.state.world[CHAINS]['done']))

    def test_interview_followup_and_cap(self):
        self.all_groups()
        self.accept('дать интервью газете кочто сегодня о работе')
        self.week()
        self.assertIsNotNone(self.chain('press_follow'))
        self.week()
        self.assertTrue(self.chain('press_follow')['announced'])
        self.accept('встретиться с молодежью о работе')
        self.week()
        self.assertEqual(self.state.world[CHAINS]['done']['press_follow']['result'], 'success')
        self.assertLessEqual(len(self.state.world[CHAINS]['active']), 3)


if __name__ == '__main__':
    unittest.main()
