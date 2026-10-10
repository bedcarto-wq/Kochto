import copy,json,tempfile,unittest,zlib,base64
from pathlib import Path
from gorod.god.world import World,validate_state,previous_data,fingerprint,event
from gorod.god import territories,crises,network
from gorod.engine import RuleError,DataError

class ScaleTests(unittest.TestCase):
 def test_city_default(self):self.assertIsNone(World(seed=1).state['territory'])
 def test_region_two_autonomous_cities(self):
  w=World(seed=1,scale='region');self.assertEqual(len(territories.cities(w.state)),2);self.assertEqual(sum(c['population'] for city in territories.cities(w.state).values() for c in city['cohorts']),48000)
 def test_federation_two_regions_four_cities(self):
  w=World(seed=1,scale='federation');self.assertEqual(len(w.state['territory']['regions']),2);self.assertEqual(len(territories.cities(w.state)),4)
 def test_unknown_scale_rejected(self):
  with self.assertRaises(RuleError):World(scale='planet')
 def test_city_scenario_cannot_be_relabelled_federal(self):
  with self.assertRaises(RuleError):World(scale='federation',scenario='last_winter')
 def test_background_cities_tick(self):
  w=World(seed=1,scale='region');old=w.state['territory']['cities']['r0:c1']['week_seed'];w.step(1,False);child=w.state['territory']['cities']['r0:c1'];self.assertEqual(child['week'],2);self.assertNotEqual(child['week_seed'],old)
 def test_camera_preserves_rng_and_influence(self):
  w=World(seed=1,scale='region');w.intervene({'power':'attention','topic':'jobs'});energy=w.state['energy'];old=w.state['week_seed'];w.territorial_action('select','r0:c1');self.assertEqual(w.state['energy'],energy);w.territorial_action('select','r0:c0');self.assertEqual(w.state['week_seed'],old)
 def test_camera_does_not_change_simulation(self):
  a=World(seed=1,scale='region');b=World(seed=1,scale='region');b.territorial_action('select','r0:c1');a.step(2,False);b.step(2,False)
  for cid in territories.cities(a.state):
   x=territories.local(territories.cities(a.state)[cid]);y=territories.local(territories.cities(b.state)[cid]);x.pop('revision');y.pop('revision');self.assertEqual(x,y)
 def test_upper_elections_have_integer_conserved_votes(self):
  w=World(seed=2,scale='federation');w.step(12,False);t=w.state['territory'];self.assertEqual(len(t['federal']['elections']),1)
  for row in [*t['regions'].values(),t['federal']]:
   e=row['elections'][0];self.assertTrue(all(type(v) is int for v in e['votes'].values()));self.assertEqual(sum(e['seats'].values()),15);self.assertTrue(row['government'])
 def test_government_program_changes_aid_priority(self):
  w=World(seed=2,scale='region');a,b=territories.cities(w.state).values()
  for d in a['districts'].values():d['jobs']=20;d['income']=20;d['pollution']=30
  for d in b['districts'].values():d['jobs']=90;d['income']=90;d['pollution']=30
  self.assertGreater(territories.priority(a,'labor',w.data),territories.priority(b,'labor',w.data))
  self.assertLess(territories.priority(a,'civic',w.data),territories.priority(b,'civic',w.data))
 def test_regional_transfer_conserves_treasuries(self):
  w=World(seed=2,scale='region');s=w.state;s['week']=4;t=s['territory'];t['regions']['r0']['government']=['labor']
  for c in territories.cities(s).values():c['week']=4
  before=sum(c['budget'] for c in territories.cities(s).values())+t['regions']['r0']['budget']
  def advance(c,data):c['week']+=1;return None
  territories.step(s,w.data,advance,lambda c,x:({},0),lambda v,n,k:{},event)
  after=sum(c['budget'] for c in territories.cities(s).values())+t['regions']['r0']['budget']
  self.assertAlmostEqual(after,before+4);self.assertEqual(t['regions']['r0']['budget'],52)
 def test_migration_preserves_population(self):
  w=World(seed=2,scale='region');w.step(13,False);self.assertEqual(sum(c['population'] for city in territories.cities(w.state).values() for c in city['cohorts']),48000)
 def test_city_switch_invalid_atomic(self):
  w=World(seed=1,scale='region');before=copy.deepcopy(w.state)
  with self.assertRaises(RuleError):w.territorial_action('select','missing')
  self.assertEqual(w.state,before)
 def test_save_continuation(self):
  a=World(seed=3,scale='region');a.step(3,False)
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'region.json';a.save(p);b=World();b.load(p);a.step(2,False);b.step(2,False);self.assertEqual(a.state,b.state)
 def test_compressed_snapshot_roundtrip(self):
  a=World(seed=2,scale='federation');obj=network.snapshot(a);self.assertEqual(obj['format'],'god-shared-zlib');b=World();network.restore(b,obj);self.assertEqual(a.state,b.state)
 def test_bad_zlib_rejected(self):
  w=World();obj=network.snapshot(World(scale='region'));obj['state']='bad'
  with self.assertRaises(DataError):network.restore(w,obj)
 def test_bomb_bounded(self):
  w=World();obj=network.snapshot(World(scale='region'));obj['state']=base64.b64encode(zlib.compress(b'x'*20_000_001)).decode()
  with self.assertRaises(DataError):network.restore(w,obj)
 def test_nested_territory_rejected(self):
  w=World(seed=2,scale='region');s=copy.deepcopy(w.state);s['territory']['cities']['r0:c1']['territory']={}
  with self.assertRaises(DataError):validate_state(s,w.data)
 def test_missing_link_graph_rejected(self):
  w=World(scale='region');w.state['territory']['links']={}
  with self.assertRaises(DataError):validate_state(w.state,w.data)
 def test_background_time_mismatch_rejected(self):
  w=World(seed=2,scale='region');s=copy.deepcopy(w.state);s['territory']['cities']['r0:c1']['week']=3
  with self.assertRaises(DataError):validate_state(s,w.data)
 def test_story086_migration_keeps_actual_history(self):
  a=World(seed=2,scenario='last_winter');a.step(3,False);s=copy.deepcopy(a.state);s.pop('territory');s.pop('crises');s['schema']=4;payload={'format':'god-world','schema':4,'rules':fingerprint(previous_data(a.data,4)),'state':s}
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'086.json';p.write_text(json.dumps({'payload':payload,'checksum':fingerprint(payload)}),encoding='utf-8');b=World();b.load(p);self.assertEqual(b.state['story'],s['story']);self.assertIsNone(b.state['territory'])
 def test_network_select_authoritative(self):
  a=World(seed=2,scale='region');obj=network.command(a,a.state['revision'],'territory',{'op':'select','value':'r0:c1'});b=World();network.restore(b,obj);self.assertEqual(a.state,b.state)
 def test_stale_request_rejected(self):
  a=World(seed=2,scale='region');a.territorial_action('select','r0:c1')
  with self.assertRaises(RuleError):network.command(a,0,'step',1)

class CrisisTests(unittest.TestCase):
 def test_three_different_dimensions(self):
  w=World(seed=1);m,c,d=crises.measures(w.state,'services');self.assertTrue(0<=m<=100 and 0<=c<=100 and 0<=d<=100)
 def test_low_pressure_does_not_create_random_crisis(self):
  w=World(seed=1);s=w.state
  for d in s['districts'].values():d['jobs']=100
  for c in s['cohorts']:c['service_pressure']=0;c['trust']['labor']=100
  crises.tick(s,w.data,event);self.assertFalse(s['crises']['items'])
 def test_problem_creates_warning(self):
  w=World(seed=1)
  for c in w.state['cohorts']:c['service_pressure']=10
  crises.tick(w.state,w.data,event);self.assertTrue(any(c['kind']=='services' and c['stage']=='warning' for c in w.state['crises']['items']))
 def test_no_inevitable_violence(self):
  w=World(seed=1);s=w.state
  for c in s['cohorts']:c['service_pressure']=6
  crises.tick(s,w.data,event);s['week']=5;crises.tick(s,w.data,event);row=next(c for c in s['crises']['items'] if c['kind']=='services');self.assertEqual(row['stage'],'negotiating')
 def test_recovery_requires_four_weeks(self):
  w=World(seed=1);s=w.state
  for c in s['cohorts']:c['service_pressure']=10
  crises.tick(s,w.data,event)
  for c in s['cohorts']:c['service_pressure']=0
  for week in range(2,6):s['week']=week;crises.tick(s,w.data,event)
  row=next(c for c in s['crises']['items'] if c['kind']=='services');self.assertEqual(row['stage'],'resolved');self.assertTrue(row['epilogue'])
 def test_recovery_interrupted(self):
  w=World(seed=1);s=w.state
  for c in s['cohorts']:c['service_pressure']=10
  crises.tick(s,w.data,event)
  for c in s['cohorts']:c['service_pressure']=0
  s['week']=2;crises.tick(s,w.data,event)
  for c in s['cohorts']:c['service_pressure']=8
  s['week']=3;crises.tick(s,w.data,event);self.assertEqual(next(c for c in s['crises']['items'] if c['kind']=='services')['low_weeks'],0)
 def test_goal_does_not_assign_winner(self):
  w=World(seed=1);parties=copy.deepcopy(w.state['parties']);w.territorial_action('goal','ties');self.assertEqual(parties,w.state['parties']);self.assertEqual(w.state['crises']['goal'],'ties')
 def test_unknown_goal_atomic(self):
  w=World(seed=1);before=copy.deepcopy(w.state)
  with self.assertRaises(RuleError):w.territorial_action('goal','win')
  self.assertEqual(w.state,before)
 def test_corrupt_dimension_rejected(self):
  w=World(seed=1);crises.tick(w.state,w.data,event);w.state['crises']['items'][0]['capacity']=-1
  with self.assertRaises(DataError):validate_state(w.state,w.data)

if __name__=='__main__':unittest.main()
