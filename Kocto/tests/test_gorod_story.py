import copy,json,tempfile,unittest
from pathlib import Path
from gorod.god.world import World,validate_state,fingerprint,previous_data,event
from gorod.god import story,network
from gorod.engine import RuleError,DataError

class StoryTests(unittest.TestCase):
 def world(self,goal='livelihood'):return World(seed=861,scenario='last_winter',goal=goal)
 def test_free_world_has_no_story(self):self.assertIsNone(World(seed=1).state['story'])
 def test_story_does_not_add_population(self):
  w=self.world();self.assertEqual(w.summary()['population'],24000);self.assertEqual(len(w.state['cohorts']),144)
 def test_four_residents_reference_existing_cohorts(self):
  w=self.world();self.assertEqual(len(w.state['story']['residents']),4);story.validate(w.state,w.data)
 def test_three_goals_do_not_assign_party(self):
  states=[self.world(g).state for g in story.GOALS]
  self.assertTrue(all(s['parties']==states[0]['parties'] for s in states))
 def test_unknown_goal_rejected(self):
  with self.assertRaises(RuleError):self.world('win_party')
 def test_deadline_is_visible_without_action(self):self.assertIn('неделе 8',' '.join(story.briefing(self.world().state)))
 def test_world_moves_without_player(self):
  w=self.world();w.step(8,False);self.assertTrue(w.state['story']['decisions']);self.assertEqual(len(w.state['story']['weekly']),3)
 def test_closed_firm_cannot_spontaneously_recruit(self):
  w=self.world();s=w.state;s['story']['plant']='closed';s['firms']['factory']['workers']=0;s['firms']['factory']['status']='закрыто';s['firms']['factory']['capital']=80;s['week']=7;w.step(1,False);self.assertEqual(w.state['firms']['factory']['workers'],0)
 def test_conversion_requires_budget(self):
  w=self.world();s=w.state;s['week']=8;s['budget']=0;s['districts']['factory']['infra']=80;s['firms']['factory']['capital']=50;s['actors']['a0']['competence']=80;story.before(s,w.data,event);self.assertNotEqual(s['story']['plant'],'converting')
 def test_conversion_spends_once_and_requires_six_steps(self):
  w=self.world();s=w.state;s['week']=8;s['budget']=100;s['districts']['factory']['infra']=80;s['actors']['a0']['competence']=80;s['firms']['factory']['capital']=50
  story.before(s,w.data,event);self.assertEqual(s['budget'],68);self.assertEqual(s['story']['progress'],1);self.assertEqual(s['story']['plant'],'converting')
  for n in range(9,14):s['week']=n;story.before(s,w.data,event)
  self.assertEqual(s['story']['plant'],'converted');self.assertEqual(s['story']['cost'],32);self.assertEqual(s['firms']['factory']['workers'],850)
 def test_weather_can_delay_conversion(self):
  w=self.world();s=w.state;s['story']['plant']='converting';s['districts']['factory']['weather']=30;story.before(s,w.data,event);self.assertEqual(s['story']['progress'],0)
 def test_same_seed_interventions_change_real_conditions(self):
  a=self.world();b=self.world()
  for n in range(8):
   if n in (0,4):
    b.intervene({'power':'economy','target':'factory','strength':15,'duration':4});b.intervene({'power':'infrastructure','target':'factory','strength':15,'duration':4})
   a.step(1,False);b.step(1,False)
  self.assertEqual(a.state['story']['plant'],'closed');self.assertEqual(b.state['story']['plant'],'converting')
  self.assertFalse(b.state['editor_used'])
 def test_resident_status_uses_actual_budget(self):
  w=self.world();r=w.state['story']['residents'][0];c=next(c for c in w.state['cohorts'] if c['id']==r['cohort']);c['household']['shortage']=100;self.assertIn('не покрыты',story.resident_status(w.state,r))
 def test_revise_goal_keeps_history_and_world(self):
  w=self.world();parties=copy.deepcopy(w.state['parties']);w.story_action('goal','ties');self.assertEqual(w.state['story']['history'][0]['old'],'livelihood');self.assertEqual(w.state['parties'],parties)
 def test_invalid_revision_is_atomic(self):
  w=self.world();before=copy.deepcopy(w.state)
  with self.assertRaises(RuleError):w.story_action('goal','wrong')
  self.assertEqual(w.state,before)
 def test_epilogue_stops_multiweek_run(self):
  w=self.world();reports=w.step(104,False);self.assertEqual(w.state['week'],27);self.assertEqual(len(reports),26);self.assertTrue(w.state['story']['finished']);self.assertTrue(w.state['story']['epilogue'])
 def test_no_auto_continue_after_epilogue(self):
  w=self.world();w.step(26,False)
  with self.assertRaises(RuleError):w.step()
 def test_continue_keeps_fixed_epilogue(self):
  w=self.world();w.step(26,False);end=copy.deepcopy(w.state['story']['epilogue']);w.story_action('continue');w.step(4,False);self.assertEqual(w.state['story']['epilogue'],end);self.assertEqual(w.state['week'],31)
 def test_epilogue_marks_direct_editor(self):
  w=self.world();w.direct({'op':'popularity','party':'labor','value':20});w.step(26,False);self.assertIn('прямой редактор',' '.join(w.state['story']['epilogue']))
 def test_continue_before_end_rejected(self):
  with self.assertRaises(RuleError):self.world().story_action('continue')
 def test_saved_story_continues_deterministically(self):
  a=self.world();a.step(10,False)
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'story.json';a.save(p);b=World();b.load(p);a.step(16,False);b.step(16,False);self.assertEqual(a.state,b.state)
 def test_network_goal_is_authoritative(self):
  a=self.world();packet=network.command(a,a.state['revision'],'story',{'op':'goal','value':'health'});b=World();network.restore(b,packet);self.assertEqual(a.state,b.state)
 def test_network_rejects_stale_revision(self):
  a=self.world();a.step()
  with self.assertRaises(RuleError):network.command(a,0,'story',{'op':'goal','value':'ties'})
 def test_corrupt_story_rejected(self):
  a=self.world();s=copy.deepcopy(a.state);s['story']['residents'][0]['cohort']='missing'
  with self.assertRaises(DataError):validate_state(s,a.data)
 def test_085_migration_is_free_not_retroactive_story(self):
  a=World(seed=861);s=copy.deepcopy(a.state);s.pop('story');s['schema']=3;old=previous_data(a.data,3);payload={'format':'god-world','schema':3,'rules':fingerprint(old),'state':s}
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'085.json';p.write_text(json.dumps({'payload':payload,'checksum':fingerprint(payload)}),encoding='utf-8');raw=p.read_bytes();a.load(p);self.assertIsNone(a.state['story']);self.assertEqual(p.read_bytes(),raw)
 def test_epilogue_does_not_declare_universal_goodness_score(self):
  a=self.world();a.step(26,False);self.assertIn('Контрфактический',' '.join(a.state['story']['epilogue']))

if __name__=='__main__':unittest.main()
