import copy
import json
import random
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch
from gorod import engine as E, intent as I, rival_ai as R
from gorod.session import Session
from gorod.multiplayer import Match, candidate, LEGACY_RULES

SK={'charm':30,'eloquence':30,'cunning':30}

class IntentsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.data=E.load_data()
    def setUp(self):
        self.s=Session(self.data);self.s.new('Анна','f',SK,seed=123)
    def test_blocked_speech_never_mutates(self):
        cases=['Не обещаю закрыть завод','Я не буду нанимать охрану','Что будет если заморозить тарифы?',
               'Ложкин сказал: «Обещаю заморозить тарифы»','Ложкин поддерживает заморозку тарифов','Он не поддерживает завод','Я не хочу участвовать во встрече с рабочими','Расскажи об обещаниях по тарифам','Подкупить председателя за тарифы','Он обещал заморозить тарифы',
               'Поддержу завод если директор поставит фильтры','Поддержу завод, но без ночных смен',
               'Обещаю снизить тарифы на 10%','Вчера пообещала заморозку тарифов',
               'Нанять охрану когда начнутся угрозы','Если тарифы приняты и директор честный, нанять охрану']
        for phrase in cases:
            with self.subTest(phrase=phrase):
                before=E.to_dict(self.s.state)
                view=self.s.understand(phrase)
                self.assertFalse(view['ready'])
                with self.assertRaises(E.RuleError):self.s.confirm()
                self.assertEqual(before,E.to_dict(self.s.state))
    def test_scope_negated_content_not_act(self):
        v=self.s.understand('Обещаю не поддерживать расширение завода за 2 недели')
        self.assertTrue(v['ready'],v)
        self.assertEqual(self.s.pending.side,-1)
    def test_explicit_negative_position(self):
        v=self.s.understand('Не поддерживаю расширение завода')
        self.assertTrue(v['ready'],v)
        self.assertEqual(self.s.pending.side,-1)
    def test_ambiguity_requires_choice(self):
        v=self.s.understand('Встретиться с рабочими и пенсионерами')
        self.assertIn('group',v['missing']);self.assertFalse(v['ready'])
        self.assertEqual(self.s.pending.group,'')
        self.assertTrue(self.s.set_slot('group','elders')['ready'])
    def test_action_correction_drops_irrelevant_ambiguity(self):
        self.s.understand('Встретиться с рабочими и пенсионерами')
        view=self.s.set_action('security')
        self.assertTrue(view['ready'],view)
        self.assertNotIn('group',view['missing'])
        self.assertIn('действие исправлено вами', ' '.join(view['notes']))
    def test_manual_negotiation_default_term(self):
        self.s.manual('negotiate')
        self.assertEqual(self.s.pending.deadline,self.data['actions']['negotiate']['default_deadline'])
    def test_no_default_positive(self):
        v=self.s.understand('Выступить о заводе')
        self.assertIn('side',v['missing']);self.assertFalse(v['ready'])
        self.assertTrue(self.s.set_slot('side',-1)['ready'])
    def test_sequence_does_not_discard_operations(self):
        v=self.s.understand('Сначала встретиться с рабочими; затем нанять охрану')
        self.assertEqual(len(v['steps']),2);self.assertTrue(v['ready'],v)
        money=self.s.state.money
        self.s.confirm()
        self.assertEqual(self.s.state.actions_left,1)
        self.assertEqual(self.s.state.money,money-self.data['actions']['meeting']['cost']-self.data['actions']['security']['cost'])
        record=self.s.state.intent_history[-1]
        self.assertEqual(record['edges'],[{'from':0,'to':1,'relation':'then'}])
        self.assertEqual(len(record['steps']),2)
        a,b=record['steps'][0]['span']
        self.assertEqual(record['text'][a:b],record['steps'][0]['text'])
    def test_invalid_later_step_rolls_back(self):
        self.s.state.security=self.data['actions']['security']['max_level']
        self.s.understand('Встретиться с рабочими; затем нанять охрану')
        before=E.to_dict(self.s.state)
        with self.assertRaises(E.RuleError):self.s.confirm()
        self.assertEqual(before,E.to_dict(self.s.state))
    def test_plan_budget_checked(self):
        self.s.state.actions_left=1
        v=self.s.understand('Встретиться с рабочими; затем нанять охрану')
        self.assertFalse(v['ready']);self.assertTrue(any('действий' in x for x in v['warnings']))
    def test_supported_condition_both_forms(self):
        for phrase in ['Если заморозка тарифов уже принята, нанять охрану','Нанять охрану если заморозка тарифов уже принята']:
            v=self.s.understand(phrase);self.assertFalse(v['ready'],v)
            self.s.state.policies['tariff_freeze']=1
            v=self.s.understand(phrase);self.assertTrue(v['ready'],v)
            self.assertEqual(len(v['steps']),1)
            self.s.state.policies['tariff_freeze']=0
    def test_condition_rechecked_after_preview(self):
        self.s.state.policies['tariff_freeze']=1
        self.s.understand('Нанять охрану если заморозка тарифов уже принята')
        self.s.state.policies['tariff_freeze']=0
        before=E.to_dict(self.s.state)
        with self.assertRaises(E.RuleError):self.s.confirm()
        self.assertEqual(before,E.to_dict(self.s.state))
    def test_full_card_memory_and_guard(self):
        self.s.understand('Встретиться с рабочими')
        self.s.set_slot('group','elders');self.s.confirm()
        v=self.s.understand('Встретиться с рабочими')
        self.assertEqual(self.s.pending.group,'elders');self.assertEqual(v['source'],'память')
        fake=asdict(E.Card('security'))
        self.s.state.intent_memory.append({'text':'не обещаю завод','card':fake})
        self.assertFalse(self.s.understand('Не обещаю завод')['ready'])
    def test_select_step_correction(self):
        self.s.understand('Встретиться с рабочими; затем выступить о заводе')
        self.s.select_step(1);self.s.set_slot('side',-1)
        self.assertTrue(self.s.view()['ready'])
        self.assertEqual(self.s.intent.steps[0].card.group,'workers')
        self.assertEqual(self.s.intent.steps[1].card.side,-1)
    def test_limits_and_unknown_condition(self):
        self.assertFalse(self.s.understand('Нанять охрану;'*5)['ready'])
        self.assertFalse(self.s.understand('я'*2001)['ready'])
        self.assertFalse(self.s.understand('Нанять охрану если директор сохранит работу')['ready'])
    def test_impossible_intention_does_not_create_entity(self):
        before=E.to_dict(self.s.state)
        view=self.s.understand('Назначить себя губернатором и создать миллиард рублей')
        self.assertFalse(view['ready'])
        self.assertEqual(before,E.to_dict(self.s.state))
    def test_improver_does_not_drop_constraints(self):
        self.assertEqual(self.s.suggest('Поддержу завод если директор поставит фильтры'), [])
        self.assertEqual(self.s.suggest('Не обещаю тарифы'), [])

    def test_memory_save_corruption_is_data_error(self):
        obj = E.to_dict(self.s.state)
        obj['intent_memory'] = [3]
        with self.assertRaises(E.DataError): E.from_dict(obj)

    def test_save_and_legacy_state(self):
        old=E.to_dict(self.s.state)
        for k in ('negotiations','intent_history','intent_memory'):old.pop(k)
        self.assertEqual(E.from_dict(old).negotiations,[])
        self.s.understand('Встретиться с рабочими');self.s.confirm()
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'game.json';self.s.save(p)
            self.assertEqual(E.to_dict(E.load_game(p)),E.to_dict(self.s.state))

class NegotiationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.data=E.load_data()
    def setUp(self):self.state=E.new_game(self.data,'Анна',SK,'f',seed=12)
    def force(self):return patch.object(E,'_roll',return_value={'tier':'success','roll':80,'total':90,'difficulty':40})
    def offer(self,side=1,term=6):
        with self.force():E.perform(self.state,self.data,E.Card('negotiate',proposal='tariff_freeze',side=side,deadline=term))
        return self.state.negotiations[-1]
    def test_counteroffer_and_explicit_acceptance(self):
        deal=self.offer();self.assertEqual(deal['status'],'offered');self.assertEqual(deal['term'],2)
        before=E.difficulty(self.state,self.data,E.Card('initiative',proposal='tariff_freeze',side=1))
        E.perform(self.state,self.data,E.Card('accept_deal'))
        self.assertEqual(deal['status'],'accepted')
        after=E.difficulty(self.state,self.data,E.Card('initiative',proposal='tariff_freeze',side=1))
        self.assertEqual(before-after,self.data['negotiation']['speaker']['initiative_bonus'])
        self.assertEqual(self.state.actions_left,1)
    def test_trust_changes_counteroffer(self):
        self.state.npc_loyalty['speaker']=70
        self.assertEqual(self.offer()['term'],3)
    def test_refusal_and_no_ghost_deal(self):
        self.state.npc_loyalty['speaker']=20
        with self.force():E.perform(self.state,self.data,E.Card('negotiate',proposal='tariff_freeze',side=1))
        self.assertEqual(self.state.negotiations,[])
        self.assertEqual(self.state.facts[-1].kind,'negotiation_reject')
        with self.assertRaises(E.RuleError):E.perform(self.state,self.data,E.Card('accept_deal'))
    def test_fulfilled_contract(self):
        self.offer();E.perform(self.state,self.data,E.Card('accept_deal'))
        loyalty=self.state.npc_loyalty['speaker']
        with self.force():E.perform(self.state,self.data,E.Card('initiative',proposal='tariff_freeze',side=1))
        self.assertEqual(self.state.negotiations[0]['status'],'fulfilled')
        self.assertGreater(self.state.npc_loyalty['speaker'],loyalty)
        self.assertTrue(any(f.kind=='deal_kept' for f in self.state.facts))
    def test_missed_deadline(self):
        deal=self.offer(term=1);E.perform(self.state,self.data,E.Card('accept_deal'))
        loyalty=self.state.npc_loyalty['speaker']
        E.resolve_deals(self.state,self.data,end=True)
        self.assertEqual(deal['status'],'broken');self.assertLess(self.state.npc_loyalty['speaker'],loyalty)
    def test_reversal_breaks_contract(self):
        deal=self.offer();E.perform(self.state,self.data,E.Card('accept_deal'))
        with self.force():E.perform(self.state,self.data,E.Card('statement',proposal='tariff_freeze',side=-1))
        self.assertEqual(deal['status'],'broken')
    def test_offer_expires_without_penalty(self):
        deal=self.offer();loyalty=self.state.npc_loyalty['speaker']
        self.state.week=deal['expires_week'];E.resolve_deals(self.state,self.data,end=True)
        self.assertEqual(deal['status'],'expired');self.assertEqual(self.state.npc_loyalty['speaker'],loyalty)
    def test_press_handles_new_facts(self):
        from gorod.press import render
        self.offer();E.perform(self.state,self.data,E.Card('accept_deal'))
        for f in self.state.facts:
            for paper in self.data['papers']:
                article=render(self.state,self.data,paper,f,random.Random(1))
                self.assertTrue(article['headline']);self.assertNotIn('{',article['lead'])
    def test_no_contract_for_completed_policy(self):
        self.state.policies['tariff_freeze']=1
        with self.assertRaises(E.RuleError):self.offer()
    def test_no_reward_for_late_acceptance(self):
        self.offer();self.state.policies['tariff_freeze']=1
        with self.assertRaises(E.RuleError):E.perform(self.state,self.data,E.Card('accept_deal'))
    def test_choose_between_two_offers(self):
        s=Session(self.data);s.state=self.state
        self.offer()
        with self.force(): E.perform(self.state,self.data,E.Card('negotiate',proposal='trade_levy',side=-1))
        view=s.understand('Принимаю предложение председателя')
        self.assertIn('proposal',view['missing']);self.assertFalse(view['ready'])
        view=s.set_slot('proposal','trade_levy');self.assertTrue(view['ready'])
        self.assertEqual(s.pending.side,-1)
        s.confirm()
        self.assertEqual(s.state.negotiations[-1]['status'],'accepted')
        self.assertEqual(s.state.negotiations[0]['status'],'offered')

    def test_acceptance_has_no_random_failure(self):
        self.offer()
        card=E.Card('accept_deal')
        self.assertEqual(E.chance(self.state,self.data,card),100)
        with patch.object(E,'_roll',side_effect=AssertionError('acceptance must not roll')):
            E.perform(self.state,self.data,card)

    def test_actual_dialogue_via_session(self):
        s=Session(self.data);s.state=self.state
        v=s.understand('Поговорить с председателем за заморозку тарифов за 6 недель')
        self.assertTrue(v['ready'],v)
        with self.force():s.confirm()
        v=s.understand('Принимаю предложение председателя');self.assertTrue(v['ready'],v)
        s.confirm();self.assertEqual(s.state.negotiations[0]['status'],'accepted')

class NetworkSemanticTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.data=E.load_data()
    def setUp(self):self.m=Match(self.data,[candidate('Анна','f',SK),candidate('Борис','m',SK)],seed=77)
    def payload(self,text):
        sess=self.m.session(0);v=sess.understand(text)
        return {'text':text,'cards':[asdict(x.card) for x in sess.intent.steps]},v
    def test_network_plan_one_revision(self):
        p,v=self.payload('Встретиться с рабочими; затем нанять охрану')
        self.assertTrue(v['ready']);self.m.command(0,0,'plan',p)
        self.assertEqual(self.m.revision,1);self.assertEqual(self.m.states[0].actions_left,1)
        restored=Match.restore(self.data,self.m.snapshot());self.assertEqual(restored.snapshot(),self.m.snapshot())
    def test_host_rejects_unsafe_text_despite_card(self):
        before=self.m.snapshot()
        payload={'text':'Не обещаю тарифы','cards':[asdict(E.Card('security'))]}
        with self.assertRaises(E.RuleError):self.m.command(0,0,'plan',payload)
        self.assertEqual(before,self.m.snapshot())
    def test_network_plan_atomic(self):
        self.m.states[0].security=self.data['actions']['security']['max_level']
        p,_=self.payload('Встретиться с рабочими; затем нанять охрану');before=self.m.snapshot()
        with self.assertRaises(E.RuleError):self.m.command(0,0,'plan',p)
        self.assertEqual(before,self.m.snapshot())
    def test_shared_policy_fulfills_other_contract(self):
        a,b=self.m.states
        with patch.object(E,'_roll',return_value={'tier':'success','roll':80,'total':90,'difficulty':40}):
            self.m.command(0,0,'action',{'card':asdict(E.Card('negotiate',proposal='tariff_freeze',side=1)),'text':''})
            self.m.command(0,1,'action',{'card':asdict(E.Card('accept_deal')),'text':''})
            self.m.command(0,2,'ready')
            self.m.command(1,3,'action',{'card':asdict(E.Card('initiative',proposal='tariff_freeze',side=1)),'text':''})
        self.assertEqual(self.m.states[0].negotiations[0]['status'],'fulfilled')
    def test_legacy_match_hash_migration(self):
        old=self.m.snapshot();old['rules']=LEGACY_RULES
        for s in old['states']:
            for key in ('negotiations','intent_history','intent_memory'):s.pop(key)
        new=Match.restore(self.data,old)
        self.assertEqual(new.states[0].negotiations,[])
        self.assertNotEqual(new.snapshot()['rules'],LEGACY_RULES)

class SharedSimulationTest(unittest.TestCase):
    def test_rival_uses_exact_engine_delta(self):
        data=E.load_data();state=E.new_game(data,'Анна',SK,'f',seed=1)
        delta={'workers':{'rival':13,'support':-7,'trust':-3}}
        scratch=copy.deepcopy(state);f=E._fact(scratch,'simulation','rival',0,0)
        E._apply(scratch,data,f,'workers',**delta['workers'])
        before=E.to_dict(state)
        self.assertAlmostEqual(R._simulate(state,data,delta),R.margin(scratch.groups,data)-R.margin(state.groups,data))
        self.assertEqual(before,E.to_dict(state))

if __name__=='__main__':unittest.main()
