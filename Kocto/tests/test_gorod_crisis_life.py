import copy,json,tempfile,unittest
from pathlib import Path
from gorod.god.world import World,event,validate_state,fingerprint,previous_data
from gorod.god import crises,crisis_life as L,network,storage,territories,living
from gorod.engine import DataError,RuleError

class LivingCrisisTests(unittest.TestCase):
 def crisis(self,kind='services'):
  w=World(seed=88);s=w.state
  for d in s['districts'].values():d['solidarity']=55;d['jobs']=20 if kind=='jobs' else 60
  for c in s['cohorts']:
   c['service_pressure']=8;c['engagement']=80;c['household']['free_time']=45
   if kind=='trust':c['trust']['labor']=20
  crises.tick(s,w.data,event);r=next(r for r in s['crises']['items'] if r['kind']==kind)
  s['week']=3;L.update(s,w.data,r,event)
  return w,r
 def agreement(self,policy='relief'):
  w,r=self.crisis('jobs');s=w.state;r['agreement']={'policy':policy,'party':'labor','district':'factory','cost':8.0,'pool':8.0,'spent':0.0,'due':12,'progress':0,'status':'executing','project':'','event':r['last_event'],'start':3,'promised':8,'benefit':0.0,'returned':0.0,'condition':'test'};return w,r
 def test_damage_not_uniform(self):
  w,r=self.crisis('jobs');self.assertGreater(len(set(round(v) for v in r['damage'].values())),1)
 def test_damage_reserve_and_debt_matter(self):
  w,r=self.crisis('jobs');c=w.state['cohorts'][0];v=L.damage(w.state,'jobs')[c['id']];c['household']['security']=0;self.assertGreater(L.damage(w.state,'jobs')[c['id']],v)
 def test_members_are_existing_people(self):
  w,r=self.crisis();cs=L.cohort_index(w.state);self.assertTrue(r['assembly']['members']);self.assertTrue(all(0<n<=cs[cid]['population'] for cid,n in r['assembly']['members'].items()))
 def test_no_time_no_organization(self):
  w=World(seed=88)
  for c in w.state['cohorts']:c['service_pressure']=8;c['household']['free_time']=0
  crises.tick(w.state,w.data,event);w.state['week']=3;crises.tick(w.state,w.data,event)
  self.assertFalse(next(r for r in w.state['crises']['items'] if r['kind']=='services')['assembly']['members'])
 def test_mandate_votes_conserve_members(self):
  w,r=self.crisis();a=r['assembly'];self.assertEqual(sum(a['votes'].values()),sum(a['members'].values()));self.assertIn(a['representative'],a['members'])
 def test_minorities_are_visible(self):
  w,r=self.crisis();self.assertGreater(sum(n>0 for n in r['assembly']['votes'].values()),1)
 def test_unknown_crisis_not_negotiated(self):
  w,r=self.crisis();w.state['week']=6;L.offer(w.state,w.data,r,event);self.assertFalse(r['offers'])
 def test_offer_pays_real_budget_after_vote(self):
  from unittest.mock import patch
  w,r=self.crisis('jobs');w.state['week']=4
  for c in w.state['cohorts']:c['known'].append(r['trigger'])
  old=w.state['budget']
  with patch.object(L,'policy_scores',return_value={'training':20,'relief':100,'conversion':10}):L.offer(w.state,w.data,r,event)
  self.assertTrue(r['offers'][-1]['accepted']);self.assertEqual(w.state['budget'],old-8);self.assertEqual(r['agreement']['pool'],8)
 def test_offer_without_money_not_signed(self):
  from unittest.mock import patch
  w,r=self.crisis('jobs');w.state['week']=4;w.state['budget']=0
  for c in w.state['cohorts']:c['known'].append(r['trigger'])
  with patch.object(L,'policy_scores',return_value={'training':20,'relief':100,'conversion':10}):L.offer(w.state,w.data,r,event)
  self.assertFalse(r['offers'][-1]['accepted']);self.assertIsNone(r['agreement']);self.assertIn('казне',r['offers'][-1]['reason'])
 def test_actual_members_can_refuse_observed_offer(self):
  from unittest.mock import patch
  w,r=self.crisis('jobs');w.state['week']=4;seen=set(list(r['assembly']['members'])[:24])
  for c in w.state['cohorts']:
   if c['id'] in seen:c['known'].append(r['trigger'])
  def scores(c,s,kind):return {'training':100 if c['id'] in seen else 0,'relief':0 if c['id'] in seen else 100,'conversion':0}
  with patch.object(L,'policy_scores',side_effect=scores):L.offer(w.state,w.data,r,event)
  self.assertFalse(r['offers'][-1]['accepted']);self.assertLess(r['offers'][-1]['share'],.55);self.assertIsNone(r['agreement'])
 def test_local_job_loss_not_hidden_by_average(self):
  w=World(seed=88)
  for d in w.state['districts'].values():d['jobs']=100
  w.state['districts']['factory']['jobs']=10;crises.tick(w.state,w.data,event)
  self.assertTrue(any(r['kind']=='jobs' for r in w.state['crises']['items']))
 def test_resources_constrain_action(self):
  w,r=self.crisis();a=r['assembly'];a['resources']=0
  for c in w.state['cohorts']:c['household']['free_time']=0
  w.state['week']=6;L.organize(w.state,r,event);self.assertEqual(a['action'],'none')
 def test_petition_not_violence(self):
  w,r=self.crisis();r['material']=40;w.state['week']=6;L.organize(w.state,r,event);self.assertEqual(r['assembly']['action'],'petition')
 def test_strike_changes_earnings(self):
  w,r=self.crisis('jobs');c=next(c for c in w.state['cohorts'] if 'worker' in c['tags']);r['assembly']['members']={c['id']:c['population']};r['assembly']['action']='strike';self.assertLess(L.labour_factor(w.state,c),1)
 def test_nonworker_not_striking(self):
  w,r=self.crisis('jobs');r['assembly']['action']='strike';c=next(c for c in w.state['cohorts'] if 'elder' in c['tags']);self.assertEqual(L.labour_factor(w.state,c),1)
 def test_escrow_payment_conserved(self):
  w,r=self.agreement();L.before(w.state,w.data,event);ag=r['agreement'];paid=sum(L.subsidy(w.state,c)*c['population']/L.TREASURY_UNIT for c in w.state['cohorts']);self.assertAlmostEqual(paid,1);self.assertAlmostEqual(ag['spent']+ag['pool']+ag['returned'],ag['cost'])
 def test_subsidy_read_does_not_double_spend(self):
  w,r=self.agreement();L.before(w.state,w.data,event);before=copy.deepcopy(r['agreement']);L.subsidy(w.state,w.state['cohorts'][0]);L.subsidy(w.state,w.state['cohorts'][0]);self.assertEqual(before,r['agreement'])
 def test_payment_independent_of_cohort_order(self):
  w,r=self.agreement();v=copy.deepcopy(w.state);v['cohorts'].reverse();L.before(w.state,w.data,event);L.before(v,w.data,event);self.assertEqual(r['agreement']['payments'],v['crises']['items'][0]['agreement']['payments'])
 def test_relief_expires_and_refunds(self):
  w,r=self.agreement();ag=r['agreement']
  for week in range(4,13):w.state['week']=week;L.before(w.state,w.data,event)
  self.assertEqual(ag['status'],'fulfilled');self.assertAlmostEqual(ag['spent'],8);self.assertAlmostEqual(ag['pool'],0)
 def test_training_is_not_instant_skill(self):
  w,r=self.agreement('training');skills=[c['household']['skill'] for c in w.state['cohorts']];L.before(w.state,w.data,event);self.assertEqual(skills,[c['household']['skill'] for c in w.state['cohorts']])
 def test_weather_delays_real_work(self):
  w,r=self.agreement();ag=r['agreement'];ag.update(policy='staff',pool=0,spent=8);w.state['districts']['factory']['weather']=30;L.before(w.state,w.data,event);self.assertEqual(ag['progress'],0)
 def test_staffing_changes_actual_facility(self):
  w,r=self.agreement();ag=r['agreement'];ag.update(policy='staff',pool=0,spent=8);before=w.state['civic']['institutions']['factory:clinic']['staff'];L.before(w.state,w.data,event);self.assertGreater(w.state['civic']['institutions']['factory:clinic']['staff'],before)
 def test_audit_needs_actual_evidence(self):
  w,r=self.agreement();ag=r['agreement'];ag.update(policy='audit',pool=0,spent=8)
  for week in range(4,10):w.state['week']=week;L.before(w.state,w.data,event)
  self.assertEqual(ag['status'],'failed');self.assertEqual(ag['benefit'],0)
 def test_goal_boundary_no_party_bonus(self):
  w=World();old=copy.deepcopy(w.state['parties']);w.territorial_action('boundary',{'metric':'health','floor':60});self.assertEqual(old,w.state['parties']);self.assertTrue(w.state['crises']['boundary_history'])
 def test_invalid_boundary_atomic(self):
  w=World();old=copy.deepcopy(w.state)
  with self.assertRaises(RuleError):w.territorial_action('boundary',{'metric':'votes','floor':100})
  self.assertEqual(old,w.state)
 def test_corrupt_membership_rejected(self):
  w,r=self.crisis();r['assembly']['members']['fake']=50
  with self.assertRaises(DataError):validate_state(w.state,w.data)
 def test_corrupt_escrow_rejected(self):
  w,r=self.agreement();r['agreement']['pool']=9
  with self.assertRaises(DataError):validate_state(w.state,w.data)
 def test_recovery_remembers_delivery(self):
  w,r=self.crisis();r['stage']='resolved';r['material']=0;L.update(w.state,w.data,r,event);self.assertTrue(w.state['crises']['memory']);self.assertTrue(r['outcome']);self.assertIn('Граница',r['epilogue'][-1])
 def test_old_crisis_not_given_fake_mandate(self):
  w,r=self.crisis();old={k:v for k,v in r.items() if k not in L.EXTRA};s=w.state;s['crises']={'items':[old],'next_id':2,'goal':None,'history':[]};L.migrate(s);self.assertFalse(old['assembly']['members']);self.assertFalse(old['offers'])
 def test_ui_description_exposes_cost_and_mandate(self):
  w,r=self.agreement();text='\n'.join(L.describe(w.state,r));self.assertIn('Мандат:',text);self.assertIn('Соглашение:',text);self.assertIn('Ответственность',text)

class CrisisTechnicalTests(unittest.TestCase):
 def test_delta_roundtrip(self):
  a=World(seed=88);b=World(seed=88);packet=network.command(a,0,'territory',{'op':'boundary','value':{'metric':'health','floor':65}},delta=True);self.assertEqual(packet['format'],'god-shared-delta');network.restore(b,packet);self.assertEqual(a.state,b.state)
 def test_delta_wrong_base_atomic(self):
  a=World(seed=88);b=World(seed=89);before=copy.deepcopy(b.state);packet=network.command(a,0,'step',1,delta=True)
  if packet['format']!='god-shared-delta':packet=network.update(a,World(seed=88).state)
  with self.assertRaises(DataError):network.restore(b,packet)
  self.assertEqual(b.state,before)
 def test_delta_bad_path_rejected(self):
  w=World(seed=88);record={'base':fingerprint(w.state),'result':fingerprint(w.state),'changes':[[['cohorts',-1,'stress'],5]]};packet={'format':'god-shared-delta','rules':fingerprint(w.data),'state':storage.encode(record)}
  with self.assertRaises(DataError):network.restore(w,packet)
 def test_compressed_save_roundtrip(self):
  w=World(seed=88,scale='federation');w.step(3,False)
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'world.json';w.save(p);self.assertEqual(json.loads(p.read_text())['payload']['format'],'god-world-zlib');v=World();v.load(p);self.assertEqual(w.state,v.state);w.step(1,False);v.step(1,False);self.assertEqual(w.state,v.state)
 def test_087_migration_preserves_all_cities(self):
  w=World(seed=88,scale='federation');s=copy.deepcopy(w.state)
  for city in territories.cities(s).values():city['schema']=5;city['crises']={'items':[],'next_id':1,'goal':None,'history':[]}
  payload={'format':'god-world','schema':5,'rules':fingerprint(previous_data(w.data,5)),'state':s}
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'087.json';p.write_text(json.dumps({'payload':payload,'checksum':fingerprint(payload)}),encoding='utf-8');v=World();v.load(p)
   self.assertEqual(v.state['territory']['meta'],s['territory']['meta']);self.assertTrue(all(c['schema']==6 for c in territories.cities(v.state).values()));self.assertEqual(v.state['week_seed'],s['week_seed'])
 def test_repeated_commands_deterministic(self):
  a=World(seed=88,scale='region');b=World(seed=88,scale='region');a.step(8,False);b.step(8,False);self.assertEqual(a.state,b.state)

if __name__=='__main__':unittest.main()
