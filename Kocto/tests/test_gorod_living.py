import copy,json,random,tempfile,unittest
from pathlib import Path
from gorod.engine import DataError
from gorod.god.world import World,fingerprint,validate_state,event,previous_data,SCHEMA
from gorod.god import living,agents,network

class HouseholdTests(unittest.TestCase):
    def setUp(self):
        self.w=World(seed=814);self.c=self.w.state['cohorts'][0];self.d=self.w.state['districts'][self.c['district']];self.cfg=self.w.data['living']
    def test_initial_budget_is_not_fake_history(self):
        self.assertFalse(self.c['household']['ledger']);self.assertEqual(self.c['household']['income'],0)
    def test_week_has_actual_transactions(self):
        self.w.step();c=self.w.state['cohorts'][0];h=c['household'];self.assertTrue(h['ledger']);self.assertGreater(h['income'],0);self.assertGreater(h['needs'],0)
    def test_money_conservation_random_cases(self):
        rng=random.Random(10)
        for _ in range(200):
            h={'savings':rng.uniform(0,20000),'debt':rng.uniform(0,30000)}
            l=living.settle(h,rng.uniform(0,6000),rng.uniform(0,7000),self.cfg)
            self.assertAlmostEqual(l['closing_savings']-l['opening_savings']-l['closing_debt']+l['opening_debt'],l['income']-l['paid']-l['interest'],places=7)
            self.assertGreaterEqual(h['savings'],0);self.assertGreaterEqual(h['debt'],0);self.assertLessEqual(h['paid'],h['needs'])
    def test_credit_limit_creates_shortage_not_money(self):
        h={'savings':0.,'debt':0.};living.settle(h,10,10000,self.cfg);self.assertLessEqual(h['debt'],80);self.assertGreater(h['shortage'],9000)
    def test_saving_and_repayment_are_real(self):
        h={'savings':100.,'debt':100.};living.settle(h,3000,1000,self.cfg);self.assertEqual(h['debt'],0);self.assertGreater(h['savings'],1000)
    def test_parent_costs_and_income_differ(self):
        p=copy.deepcopy(self.c);p['tags'].append('parent') if 'parent' not in p['tags'] else None
        self.assertGreater(sum(living.expenses(p,self.d,self.cfg).values()),sum(living.expenses(self.c,self.d,self.cfg).values()))
        self.assertGreater(living.earnings(p,self.d,self.cfg),living.earnings(self.c,self.d,self.cfg))
    def test_unavailable_study_not_chosen(self):
        self.c['household']['savings']=0;self.c['household']['security']=10
        living.decide(self.c,self.d,self.cfg,4)
        self.assertNotIn('study',[r['action'] for r in self.c['life']['options']])
    def test_work_is_a_choice_with_time_cost(self):
        h=self.c['household'];h.update(security=0,savings=0,debt=10000,shortage=1000)
        living.decide(self.c,self.d,self.cfg,4);self.assertEqual(self.c['life']['action'],'work')
        before=living.earnings(self.c,self.d,self.cfg);self.c['life']['action']='reserve';self.assertGreater(before,living.earnings(self.c,self.d,self.cfg))
    def test_course_takes_eight_paid_weeks(self):
        h=self.c['household'];h.update(savings=100000,security=80);self.c['income']=80;self.c['life'].update(action='study',remaining=8)
        for week in range(2,9):
            self.w.state['week']=week;living.tick(self.w.state,self.w.data,random.Random(week),event)
        self.assertEqual(h['skill'],0);self.assertEqual(h['training'],7)
        self.w.state['week']=9;living.tick(self.w.state,self.w.data,random.Random(9),event)
        self.assertEqual(h['skill'],5);self.assertEqual(self.c['life']['completed'],1)
    def test_hardship_affects_stress_not_editor(self):
        self.c['income']=0;self.c['household'].update(savings=0,debt=100000);self.c['stress']=0
        self.w.state['week']=2;living.tick(self.w.state,self.w.data,random.Random(1),event)
        self.assertGreater(self.c['stress'],0);self.assertFalse(self.w.state['editor_used']);self.assertNotIn('editor_bonus',self.c)
    def test_retirement_stops_work_plan(self):
        self.c['tags']=[t for t in self.c['tags'] if t!='student']+['elder'];self.c['life']['action']='work';self.w.state['week']=2
        living.tick(self.w.state,self.w.data,random.Random(1),event);self.assertNotIn(self.c['life']['action'],('work','study'))
    def test_migrants_take_financial_stocks(self):
        origin=self.c;dest=copy.deepcopy(origin);dest['population']=100;dest['household']['savings']=10000;origin['household']['savings']=2000
        before=origin['population']*2000+100*10000
        living.transfer_mean(origin,dest,20);origin['population']-=20;dest['population']+=20
        self.assertAlmostEqual(origin['population']*origin['household']['savings']+dest['population']*dest['household']['savings'],before)
    def test_corrupt_ledger_rejected(self):
        self.w.step();self.w.state['cohorts'][0]['household']['ledger']['deposit']=-1
        with self.assertRaises(DataError):validate_state(self.w.state,self.w.data)
    def test_financial_records_bounded(self):
        self.w.step(52,False)
        self.assertTrue(all(len(c['household']['history'])<=16 for c in self.w.state['cohorts']))

class PoliticalPlannerTests(unittest.TestCase):
    def setUp(self):self.w=World(seed=814);self.p=self.w.state['parties']['labor'];self.p['intel']=agents.survey(self.w.state,self.w.data,'labor',random.Random(12))
    def test_sample_has_bounded_noisy_observations(self):
        self.assertEqual(self.p['intel']['sample'],24);self.assertEqual(len(self.p['intel']['districts']),4)
        self.assertNotEqual(self.p['intel']['districts']['factory']['jobs'],self.w.state['districts']['factory']['jobs'])
    def test_decision_does_not_read_unobserved_real_preferences(self):
        a=agents.choose(self.w.state,self.w.data,'labor')
        for c in self.w.state['cohorts']:
            c['ideology']['economy']=100;c['attention']['jobs']=0;c['household']['security']=0
        self.assertEqual(a,agents.choose(self.w.state,self.w.data,'labor'))
    def test_resources_limit_available_actions(self):
        self.p['funds']=0;_,rows=agents.choose(self.w.state,self.w.data,'labor')
        self.assertTrue(all(agents.COST[r['action']]==0 for r in rows))
    def test_stale_knowledge_encourages_listening(self):
        self.w.state['week']=50;c,_=agents.choose(self.w.state,self.w.data,'labor');self.assertEqual(c['action'],'listen')
    def test_organization_spends_funds_and_changes_capacity(self):
        old=self.p['organization'];money=self.p['funds']
        e=agents.perform(self.w.state,self.w.data,'labor',{'action':'organize','target':'factory','topic':'jobs'},random.Random(1),event)
        self.assertEqual(self.p['funds'],money-10);self.assertGreater(self.p['organization'],old);self.assertEqual(e['kind'],'organization')
    def test_listening_refreshes_knowledge(self):
        self.w.state['week']=7;agents.perform(self.w.state,self.w.data,'labor',{'action':'listen','target':'factory','topic':'jobs'},random.Random(1),event)
        self.assertEqual(self.p['intel']['week'],7)
    def test_explanation_and_alternatives_persist(self):
        self.w.step(3,False);a=self.w.state['actors'][self.w.state['parties']['labor']['leader']]
        self.assertEqual(a['decision']['week'],3);self.assertGreater(len(a['decision']['options']),2);self.assertTrue(a['decision']['reason'])
    def test_character_changes_promise_score(self):
        a=self.w.state['actors'][self.p['leader']];a['honesty']=0;_,rows=agents.choose(self.w.state,self.w.data,'labor');lo=next(r['score'] for r in rows if r['action']=='promise')
        a['honesty']=100;_,rows=agents.choose(self.w.state,self.w.data,'labor');hi=next(r['score'] for r in rows if r['action']=='promise');self.assertGreater(lo,hi)
    def test_campaign_fatigue_changes_choice(self):
        before=agents.choose(self.w.state,self.w.data,'labor')
        for did in self.p['intel']['districts']:
            for t in self.w.data['topics']:self.p['fatigue'][did+':'+t]=100
        _,rows=agents.choose(self.w.state,self.w.data,'labor');self.assertLess(next(r['score'] for r in rows if r['action']=='campaign'),0)
    def test_old_network_rules_rejected(self):
        obj=network.snapshot(self.w);obj['rules']='b87796db80f1ae89dd7a1d26350e685327932aa2b43a4c169a06587b0a07c00b'
        with self.assertRaises(DataError):network.restore(self.w,obj)
    def test_save_continuation_with_plans(self):
        self.w.step(20,False)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'мир.json';self.w.save(p);other=World(seed=1);other.load(p);self.w.step(20,False);other.step(20,False);self.assertEqual(self.w.state,other.state)
    def test_split_and_successor_have_fresh_planners(self):
        from gorod.god.world import create_party,retire_actor
        pid=create_party(self.w.state,self.w.data,'Новая',dict(self.p['ideology']));self.assertIn('intel',self.w.state['parties'][pid])
        retire_actor(self.w.state,self.w.data,self.p['leader'],'тест');a=self.w.state['actors'][self.p['leader']];self.assertEqual(a['decision']['week'],0)

class MigrationTests(unittest.TestCase):
    def old_save(self,path):
        w=World(seed=871);s=copy.deepcopy(w.state);s['schema']=1;s.pop('civic')
        for c in s['cohorts']:del c['household'];del c['life'];del c['service_pressure'];del c['service_cause']
        for a in s['actors'].values():del a['decision']
        for p in s['parties'].values():del p['intel'];del p['intent']
        data=previous_data(w.data,1)
        obj={'payload':{'format':'god-world','schema':1,'rules':fingerprint(data),'state':s}};obj['checksum']=fingerprint(obj['payload']);path.write_text(json.dumps(obj,ensure_ascii=False),encoding='utf-8');return s,obj
    def test_080_migration_preserves_world_and_seed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'old.json';old,_=self.old_save(p);w=World(seed=1);w.load(p)
            for k in ('population','id','ideology','trust'):self.assertEqual(old['cohorts'][0][k],w.state['cohorts'][0][k])
            for k in ('seed','week_seed','week','events','elections','governing'):self.assertEqual(old[k],w.state[k])
            self.assertEqual(w.state['schema'],SCHEMA);self.assertTrue(w.migration_notice);self.assertIn('household',w.state['cohorts'][0]);w.step()
    def test_unknown_legacy_rules_rejected_atomically(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'old.json';_,obj=self.old_save(p);obj['payload']['rules']='custom';obj['checksum']=fingerprint(obj['payload']);p.write_text(json.dumps(obj),encoding='utf-8');w=World(seed=1);before=copy.deepcopy(w.state)
            with self.assertRaises(DataError):w.load(p)
            self.assertEqual(w.state,before)
    def test_migration_does_not_rewrite_source(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'old.json';self.old_save(p);before=p.read_bytes();w=World();w.load(p);self.assertEqual(p.read_bytes(),before)
    def test_corrupt_new_fields_rejected(self):
        w=World()
        for mutate in (lambda s:s['cohorts'][0]['household'].__setitem__('savings',-1),lambda s:s['parties']['labor']['intel'].__setitem__('sample',100000)):
            bad=copy.deepcopy(w.state);mutate(bad)
            with self.assertRaises(DataError):validate_state(bad,w.data)

if __name__=='__main__':unittest.main()
