import copy,json,tempfile,unittest
from pathlib import Path
from gorod.god.world import World,validate_state,fingerprint,previous_data
from gorod.god import upper_politics as U,territories,network
from gorod.engine import DataError

class UpperPoliticsTests(unittest.TestCase):
 def test_city_has_no_upper_orgs(self):self.assertIsNone(World().state['territory'])
 def test_region_has_one_level(self):self.assertEqual(set(World(scale='region').state['territory']['politics']),{'r0'})
 def test_federation_has_three_levels(self):self.assertEqual(set(World(scale='federation').state['territory']['politics']),{'r0','r1','federal'})
 def test_scoped_leaders_not_same_objects(self):
  w=World(scale='federation');levels=w.state['territory']['politics'];ids=[b['leader']['id'] for level in levels.values() for b in level['branches'].values()];self.assertEqual(len(ids),len(set(ids)))
 def test_branch_funds_independent(self):
  w=World(scale='federation');t=w.state['territory'];t['politics']['r0']['branches']['labor']['funds']=1;self.assertEqual(t['politics']['r1']['branches']['labor']['funds'],60)
 def test_survey_sample_bounded_and_scoped(self):
  w=World(seed=89,scale='federation');w.step(4,False);t=w.state['territory']
  self.assertEqual(len(t['politics']['federal']['branches']['labor']['intel']['sample']),24)
  self.assertEqual(len(t['politics']['r0']['branches']['labor']['intel']['sample']),12)
  self.assertTrue(all(r['city'].startswith('r0:') for r in t['politics']['r0']['branches']['labor']['intel']['sample']))
 def test_campaigns_actual_and_costed(self):
  w=World(seed=89,scale='region');w.step(8,False);b=w.state['territory']['politics']['r0']['branches']['labor'];self.assertEqual(b['decision']['action'],'campaign');self.assertLess(b['funds'],60+8*.75)
 def test_programme_is_not_instantly_known(self):
  w=World(seed=89,scale='region');t=w.state['territory'];city=w.state;c=city['cohorts'][0];pid='labor';k=t['politics']['r0']['voters']['r0:c0/'+c['id']][pid];old=copy.deepcopy(k['perceived']);t['politics']['r0']['branches'][pid]['ideology']['economy']=100;self.assertEqual(k['perceived'],old)
 def test_different_levels_have_different_ballots(self):
  w=World(seed=89,scale='federation');t=w.state['territory'];c=w.state['cohorts'][0];key='r0:c0/'+c['id']
  for pid,k in t['politics']['federal']['voters'][key].items():k['perceived']['economy']=100 if pid=='labor' else -70
  local=U.choice(t,'r0','r0:c0',w.state,c)[0];fed=U.choice(t,'federal','r0:c0',w.state,c)[0];self.assertNotEqual(local,fed)
 def test_transfer_visibility_not_popularity(self):
  w=World(seed=89,scale='region');t=w.state['territory'];t['regions']['r0']['government']=['labor'];before=copy.deepcopy(t['politics']['r0']['voters']);U.aid(t,'r0','r0:c0',12,1);self.assertEqual(before,t['politics']['r0']['voters']);self.assertEqual(t['politics']['r0']['facts'][-1]['kind'],'transfer')
 def test_federal_transfer_scoped_to_recipient_region(self):
  w=World(seed=89,scale='federation');t=w.state['territory'];t['federal']['government']=['labor'];U.aid(t,'federal','r1',16,1);self.assertEqual(set(t['politics']['federal']['facts'][-1]['cities']),{'r1:c0','r1:c1'});validate_state(w.state,w.data)
 def test_programme_changes_actual_aid_priority(self):
  w=World(seed=89,scale='region');t=w.state['territory'];a,b=territories.cities(w.state).values()
  for d in a['districts'].values():d['jobs']=20;d['income']=20;d['pollution']=30
  for d in b['districts'].values():d['jobs']=90;d['income']=90;d['pollution']=30
  t['politics']['r0']['branches']['labor']['ideology']['economy']=-100;d=U.policy_data(t,'r0',w.data);self.assertGreater(territories.priority(a,'labor',d),territories.priority(b,'labor',d))
  t['politics']['r0']['branches']['labor']['ideology']['economy']=100;d=U.policy_data(t,'r0',w.data);self.assertLess(territories.priority(a,'labor',d),territories.priority(b,'labor',d))
 def test_forecast_sums_to_100(self):
  w=World(seed=89,scale='federation');shares,turnout=U.forecast(w.state['territory'],'federal',territories.cities(w.state));self.assertAlmostEqual(sum(shares.values()),100);self.assertTrue(0<=turnout<=100)
 def test_save_continuation(self):
  w=World(seed=89,scale='region');w.step(8,False)
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'world.json';w.save(p);v=World();v.load(p);w.step(4,False);v.step(4,False);self.assertEqual(w.state,v.state)
 def test_camera_cannot_change_upper_elections(self):
  a=World(seed=89,scale='region');b=World(seed=89,scale='region');b.territorial_action('select','r0:c1');a.step(12,False);b.step(12,False);self.assertEqual(a.state['territory']['politics'],b.state['territory']['politics']);self.assertEqual(a.state['territory']['regions'],b.state['territory']['regions'])
 def test_missing_voter_rejected(self):
  w=World(scale='region');w.state['territory']['politics']['r0']['voters'].pop('r0:c0/c0')
  with self.assertRaises(DataError):validate_state(w.state,w.data)
 def test_foreign_sample_rejected(self):
  w=World(seed=89,scale='region');w.step(4,False);w.state['territory']['politics']['r0']['branches']['labor']['intel']['sample'][0]['city']='r1:c0'
  with self.assertRaises(DataError):validate_state(w.state,w.data)
 def test_088_migration_no_fictional_campaign_history(self):
  w=World(seed=89,scale='federation');s=copy.deepcopy(w.state);s['territory'].pop('politics')
  for city in territories.cities(s).values():city['schema']=6
  payload={'format':'god-world','schema':6,'rules':fingerprint(previous_data(w.data,6)),'state':s}
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'088.json';p.write_text(json.dumps({'payload':payload,'checksum':fingerprint(payload)}),encoding='utf-8');v=World();v.load(p)
   self.assertEqual(v.state['week_seed'],s['week_seed']);self.assertTrue(all(not level['facts'] for level in v.state['territory']['politics'].values()));self.assertTrue(list(Path(d).glob('*.bak')))
 def test_network_roundtrip(self):
  w=World(seed=89,scale='federation');w.step(8,False);v=World();network.restore(v,network.snapshot(w));self.assertEqual(w.state,v.state)

if __name__=='__main__':unittest.main()
