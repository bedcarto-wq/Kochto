import copy,json,random,tempfile,unittest
from pathlib import Path
from gorod.engine import RuleError,DataError
from gorod.god.world import World,event,validate_state,previous_data,fingerprint,attraction
from gorod.god import civic,language,network

class ZeroRandom:
    def random(self):return 0.

class CivicTests(unittest.TestCase):
    def setUp(self):self.w=World(seed=851);self.s=self.w.state;self.d=self.w.data;self.z=self.s['civic'];self.i=self.z['institutions']['factory:clinic']
    def project(self,pid='labor'):
        return civic.propose(self.s,self.d,pid,self.i['id'],event)
    def test_initial_real_capacity_not_fake_completion(self):
        self.assertEqual(len(self.z['institutions']),12);self.assertGreater(self.i['queue'],0);self.assertLess(self.i['served'],self.i['demand'])
    def test_building_without_staff_not_full_service(self):
        self.i['staff']=0;civic.evaluate_institutions(self.s,self.d,event,False);self.assertEqual(self.i['served'],0);self.assertEqual(self.i['queue'],self.i['demand'])
    def test_capacity_conservation(self):
        for i in self.z['institutions'].values():self.assertAlmostEqual(i['served']+i['queue'],i['demand'])
    def test_overload_affects_time_stress_attention(self):
        c=self.s['cohorts'][0];before=(c['stress'],c['attention']['services'],c['household']['free_time']);civic.evaluate_institutions(self.s,self.d,event)
        self.assertGreater(c['stress'],before[0]);self.assertGreater(c['attention']['services'],before[1]);self.assertLess(c['household']['free_time'],before[2])
    def test_project_proposal_does_not_spend_or_improve(self):
        before=(self.s['budget'],self.i['capacity']);p=self.project();self.assertEqual(p['stage'],'proposed');self.assertEqual((self.s['budget'],self.i['capacity']),before)
    def test_stages_require_successive_weeks(self):
        p=self.project();self.s['week']=2;civic.project_tick(self.s,self.d,ZeroRandom(),event);self.assertEqual(p['stage'],'approved')
        self.s['week']=3;civic.project_tick(self.s,self.d,ZeroRandom(),event);self.assertEqual(p['stage'],'funded');self.assertEqual(p['spent'],p['cost'])
        self.assertEqual(self.i['capacity'],self.d['districts']['factory']['population']*self.d['civic']['demand']['clinic']*(.65+self.d['districts']['factory']['infra']/200))
        self.s['week']=4;civic.project_tick(self.s,self.d,ZeroRandom(),event);self.assertEqual(p['stage'],'building')
    def test_unfunded_project_waits(self):
        p=self.project();p['stage']='approved';p['due']=1;self.s['budget']=0
        civic.project_tick(self.s,self.d,ZeroRandom(),event);self.assertEqual(p['stage'],'approved');self.assertEqual(p['spent'],0)
    def test_opposition_can_be_rejected(self):
        p=self.project('civic');self.s['week']=2;civic.project_tick(self.s,self.d,ZeroRandom(),event);self.assertEqual(p['stage'],'rejected')
    def test_no_duplicate_active_projects(self):
        self.project();self.assertIsNone(self.project())
    def test_completed_project_changes_capacity_only_at_operation(self):
        p=self.project();p.update(stage='staffing',due=1,recruited=90,progress=100);old=self.i['capacity'];civic.project_tick(self.s,self.d,ZeroRandom(),event)
        self.assertEqual(p['stage'],'operating');self.assertGreater(self.i['capacity'],old)
    def test_staff_recruitment_not_instant(self):
        p=self.project();p.update(stage='staffing',due=1,recruited=0,progress=100);old=self.i['capacity'];civic.project_tick(self.s,self.d,ZeroRandom(),event)
        self.assertEqual(p['stage'],'staffing');self.assertEqual(self.i['capacity'],old)
    def test_groups_are_existing_people_not_new_population(self):
        self.s['week']=4;total=sum(c['population'] for c in self.s['cohorts']);civic.associations(self.s,self.d,ZeroRandom(),event)
        self.assertTrue(self.z['associations']);self.assertEqual(sum(c['population'] for c in self.s['cohorts']),total)
        for g in self.z['associations']:
            for cid,n in g['members'].items():self.assertLessEqual(n,next(c['population'] for c in self.s['cohorts'] if c['id']==cid))
    def test_group_has_demand_resources_and_leader(self):
        self.s['week']=4;civic.associations(self.s,self.d,ZeroRandom(),event);g=self.z['associations'][0];self.assertIn(g['leader'],g['members']);self.assertGreater(g['demand'],0)
    def test_group_retires_only_after_real_improvement(self):
        self.s['week']=4;civic.associations(self.s,self.d,ZeroRandom(),event);g=self.z['associations'][0];self.z['institutions'][g['institution']]['delay']=0;civic.associations(self.s,self.d,ZeroRandom(),event);self.assertFalse(g['active'])
    def test_party_cannot_see_unknown_group(self):
        self.s['week']=4;civic.associations(self.s,self.d,ZeroRandom(),event);civic.political_response(self.s,self.d,'labor',ZeroRandom(),event)
        self.assertTrue(all(not g['positions'] for g in self.z['associations']))
    def test_known_group_causes_real_party_response(self):
        self.s['week']=4;civic.associations(self.s,self.d,ZeroRandom(),event);g=self.z['associations'][0];actor=self.s['actors'][self.s['parties']['labor']['leader']];c=next(c for c in self.s['cohorts'] if c['district']==actor['district']);c['known'].append(g['origin'])
        civic.political_response(self.s,self.d,'labor',ZeroRandom(),event);self.assertIn('labor',g['positions'])
    def test_document_is_snapshot_not_rewritten(self):
        p=self.project();doc=self.z['documents'][-1];p['stage']='building';p['spent']=20;self.assertEqual(doc['stage'],'proposed');self.assertEqual(doc['spent'],0)
    def evidence(self):
        p=self.project();p.update(stage='building',progress=50,spent=26,public_open=True)
        claim=civic.document(self.s,'opening_claim',p,event,True);act=civic.document(self.s,'status',p,event,False);act['access']=1
        return p,claim,act
    def test_investigation_needs_two_real_documents(self):
        self.evidence();civic.investigations(self.s,self.d,ZeroRandom(),event);self.assertEqual(len(self.z['cases']),1);self.assertEqual(self.z['cases'][0]['stage'],'checking')
        self.s['week']=3;civic.investigations(self.s,self.d,ZeroRandom(),event);self.assertEqual(self.z['cases'][0]['result'],'преждевременное объявление')
    def test_no_investigation_from_invented_scandal(self):
        event(self.s,'scandal','Случайный текст',party='labor');civic.investigations(self.s,self.d,ZeroRandom(),event);self.assertFalse(self.z['cases'])
    def test_no_premature_publication(self):
        self.evidence();civic.investigations(self.s,self.d,ZeroRandom(),event);self.assertFalse(any(e['kind']=='investigation' for e in self.s['events']))
    def test_discovery_only_existing_document(self):
        before=copy.deepcopy(self.s)
        with self.assertRaises(RuleError):self.w.intervene({'power':'discovery','document_id':'D999'})
        self.assertEqual(self.w.state,before)
    def test_discovery_does_not_forge_or_force_publication(self):
        self.project();before=copy.deepcopy(self.z['documents'][-1]);self.w.intervene({'power':'discovery','document_id':before['id']})
        doc=self.w.state['civic']['documents'][-1];self.assertGreater(doc['access'],before['access']);self.assertEqual(doc['stage'],before['stage']);self.assertEqual(doc['published'],before['published'])
    def test_encounter_can_be_refused(self):
        self.w.intervene({'power':'encounter','actor_a':'a0','actor_b':'a1'});s=self.w.state;s['week']=2;s['actors']['a0']['relations']['a1']=-100;s['actors']['a1']['relations']['a0']=-100
        civic.meetings(s,self.d,random.Random(4),event);self.assertEqual(s['civic']['meetings'][0]['status'],'refused')
    def test_encounter_changes_relationship_not_party_result(self):
        self.w.intervene({'power':'encounter','actor_a':'a0','actor_b':'a1'});s=self.w.state;s['week']=2;s['actors']['a0']['relations']['a1']=80;s['actors']['a1']['relations']['a0']=80
        civic.meetings(s,self.d,ZeroRandom(),event);self.assertEqual(s['civic']['meetings'][0]['status'],'met');self.assertFalse(s['editor_used']);self.assertNotIn('editor_bonus',s['cohorts'][0])
    def test_self_encounter_invalid_atomic(self):
        before=copy.deepcopy(self.w.state)
        with self.assertRaises(RuleError):self.w.intervene({'power':'encounter','actor_a':'a0','actor_b':'a0'})
        self.assertEqual(self.w.state,before)
    def test_free_time_only_targeted_cohorts(self):
        other=World(seed=851);self.w.intervene({'power':'free_time','target':'factory','strength':15});self.w.step();other.step()
        a=self.w.state['cohorts'][0];b=other.state['cohorts'][0];self.assertGreater(a['household']['free_time'],b['household']['free_time'])
        a=self.w.state['cohorts'][36];b=other.state['cohorts'][36];self.assertEqual(a['household']['free_time'],b['household']['free_time'])
    def test_coordination_requires_existing_group(self):
        before=copy.deepcopy(self.s)
        with self.assertRaises(RuleError):self.w.intervene({'power':'coordination'})
        self.assertEqual(self.w.state,before)
    def test_coordination_preserves_demands_and_leader(self):
        self.s['week']=4;civic.associations(self.s,self.d,ZeroRandom(),event);g=copy.deepcopy(self.z['associations'][0]);self.w.intervene({'power':'coordination','association_id':g['id']})
        new=self.w.state['civic']['associations'][0];self.assertEqual((g['demand'],g['leader']),(new['demand'],new['leader']))
    def test_causal_chain_and_missing_ancestor_honest(self):
        a=event(self.s,'one','Исходная причина');b=event(self.s,'two','Следствие',causes=[a['id']]);rows=civic.ancestry(self.s,b['id']);self.assertEqual([x['id'] for x in rows],[b['id'],a['id']])
        self.assertTrue(civic.ancestry(self.s,999)[0]['missing'])
    def test_new_text_powers(self):
        self.project();self.assertTrue(language.parse(self.w,'Облегчить обнаружение документа D1').ready)
        self.assertTrue(language.parse(self.w,'Создать возможность встречи a0 и a3').ready)
        self.assertTrue(language.parse(self.w,'Освободить время рабочих').ready)
    def test_new_text_guards(self):
        for text in ('Не освобождать время рабочих','Обнаружить документ D999','Создать возможность встречи a0 и a0','Облегчить координацию объединения G999'):
            self.assertFalse(language.parse(self.w,text).ready,text)
    def test_network_uses_same_validation(self):
        before=copy.deepcopy(self.s)
        with self.assertRaises(RuleError):network.command(self.w,0,'plan','Обнаружить документ D999')
        self.assertEqual(self.w.state,before)
    def test_corrupt_civic_state_rejected(self):
        for mutate in (lambda s:s['civic']['institutions']['factory:clinic'].__setitem__('queue',-1),lambda s:s['civic'].__setitem__('next_project',0)):
            bad=copy.deepcopy(self.s);mutate(bad)
            with self.assertRaises(DataError):validate_state(bad,self.d)
    def test_continuation_with_projects_documents_groups(self):
        self.w.step(16,False)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'мир.json';self.w.save(p);other=World();other.load(p);self.w.step(16,False);other.step(16,False);self.assertEqual(self.w.state,other.state)
    def test_081_migration_preserves_households_and_seed(self):
        old=copy.deepcopy(self.s);old.pop('territory',None);old.pop('crises',None);old.pop('story',None);old.pop('civic');old['schema']=2
        for c in old['cohorts']:del c['service_pressure'];del c['service_cause']
        payload={'format':'god-world','schema':2,'rules':fingerprint(previous_data(self.d,2)),'state':old}
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'old.json';p.write_text(json.dumps({'payload':payload,'checksum':fingerprint(payload)},ensure_ascii=False),encoding='utf-8');other=World();other.load(p)
            self.assertEqual(other.state['cohorts'][0]['household'],old['cohorts'][0]['household']);self.assertEqual(other.state['week_seed'],old['week_seed']);self.assertEqual(other.state['schema'],6)
    def test_legacy_paid_project_not_paid_twice(self):
        old=copy.deepcopy(self.s);old.pop('territory',None);old.pop('crises',None);old.pop('story',None);old.pop('civic');old['schema']=2
        for c in old['cohorts']:del c['service_pressure'];del c['service_cause']
        old['projects']=[{'party':'labor','district':'factory','field':'infra','topic':'services','started':1,'finish':3,'quality':50,'gain':8}]
        payload={'format':'god-world','schema':2,'rules':fingerprint(previous_data(self.d,2)),'state':old}
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'old.json';p.write_text(json.dumps({'payload':payload,'checksum':fingerprint(payload)}),encoding='utf-8');other=World();other.load(p);self.assertEqual(other.state['projects'][0]['spent'],22);self.assertEqual(other.state['budget'],old['budget'])

if __name__=='__main__':unittest.main()
