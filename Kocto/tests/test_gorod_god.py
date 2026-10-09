import copy
import json
import tempfile
import unittest
from pathlib import Path
from gorod.engine import RuleError,DataError
from gorod.god.world import World,base_attraction,attraction,affected,forecast,allocate,election,validate_state,fingerprint,retire_actor,event
from gorod.god.language import parse,execute
from gorod.god import network as N

class GodWorldTest(unittest.TestCase):
    def setUp(self):self.w=World(seed=87)
    def test_formula_one_axis(self):self.assertAlmostEqual(base_attraction({'economy':-75},{'economy':-60},{'economy':1}),92.5)
    def test_extremes_and_weights(self):
        self.assertEqual(base_attraction({'x':-100},{'x':100},{'x':1}),0)
        self.assertEqual(base_attraction({'x':10},{'x':10},{'x':2}),100)
        with self.assertRaises(RuleError):base_attraction({'x':0},{'x':0},{'x':0})
    def test_unique_population_and_overlapping_tags(self):
        s=self.w.state;self.assertEqual(sum(c['population'] for c in s['cohorts']),24000);self.assertEqual(len(s['cohorts']),144)
        self.assertGreater(sum(sum(c['population'] for c in affected(s,t)) for t in self.w.data['tags']),24000)
        self.assertTrue(affected(s,'factory&worker'));self.assertTrue(affected(s,'worker|elder'))
    def test_choice_separate_from_attraction(self):
        from gorod.god.world import choice
        c=self.w.state['cohorts'][0];probs,t=choice(self.w.state,c)
        self.assertAlmostEqual(sum(probs.values()),1);self.assertTrue(0<t<1)
        self.assertTrue(all(0<=attraction(self.w.state,c,p)[0]<=100 for p in probs))
    def test_autonomy_without_god(self):
        before=copy.deepcopy(self.w.state);self.w.step(52,False)
        s=self.w.state;self.assertGreater(len(s['events']),30);self.assertEqual(len(s['elections']),2);self.assertTrue(s['promises'])
        self.assertNotEqual(before['districts'],s['districts']);self.assertTrue(any(e['kind']=='policy' for e in s['events']))
        self.assertFalse(s['editor_used'])
    def test_deterministic_chunked_weeks(self):
        other=World(seed=87);self.w.step(15,False)
        for _ in range(15):other.step()
        self.assertEqual(self.w.state,other.state)
    def test_stop_at_first_election(self):
        reports=self.w.step(104,True);self.assertEqual(self.w.state['week'],13);self.assertEqual(len(reports),12);self.assertTrue(reports[-1]['election'])
    def test_multiple_elections_not_game_over(self):
        self.w.step(80,False);self.assertEqual(len(self.w.state['elections']),3);self.assertEqual(self.w.state['week'],81)
    def test_population_conservation_migration(self):
        self.w.step(26,False);self.assertEqual(sum(c['population'] for c in self.w.state['cohorts']),24000)
        self.assertTrue(any(e['kind']=='migration' for e in self.w.state['events']))
    def test_election_exact_vote_count(self):
        self.w.step(12,False);e=self.w.state['elections'][-1]
        self.assertEqual(sum(e['votes'].values()),e['voters']);self.assertLessEqual(e['voters'],e['population']);self.assertEqual(sum(e['seats'].values()),15)
    def test_election_systems(self):
        for system in ('majoritarian','mixed'):
            w=World(seed=87);w.direct({'op':'rules','key':'election_system','value':system});w.step(12,False)
            e=w.state['elections'][-1];self.assertEqual(sum(e['seats'].values()),4 if system=='majoritarian' else 15)
    def test_threshold_and_dhondt(self):
        seats=allocate({'a':60,'b':39,'c':1},15,5);self.assertEqual(seats['c'],0);self.assertEqual(sum(seats.values()),15)
    def test_indirect_not_direct_bonus(self):
        before=copy.deepcopy(self.w.state);self.w.intervene({'power':'attention','target':'worker','topic':'ecology'})
        self.assertFalse(self.w.state['editor_used'])
        self.assertTrue(all('editor_bonus' not in c for c in self.w.state['cohorts']))
        self.w.step();workers=affected(self.w.state,'worker')
        self.assertGreater(workers[0]['attention']['ecology'],before['cohorts'][workers[0]['id'] and int(workers[0]['id'][1:])]['attention']['ecology'])
    def test_effect_expiry(self):
        self.w.intervene({'power':'weather','target':'riverside','strength':20,'duration':1});self.w.step()
        self.assertEqual(self.w.state['districts']['riverside']['weather'],20)
        self.w.step();self.assertEqual(self.w.state['districts']['riverside']['weather'],0)
    def test_energy_validation_atomic(self):
        before=copy.deepcopy(self.w.state)
        with self.assertRaises(RuleError):self.w.intervene({'power':'weather','target':'missing'})
        self.assertEqual(self.w.state,before)
        self.w.state['energy']=0;before=copy.deepcopy(self.w.state)
        with self.assertRaises(RuleError):self.w.intervene({'power':'weather'})
        self.assertEqual(self.w.state,before)
    def test_reveal_existing_fact_only(self):
        with self.assertRaises(RuleError):self.w.intervene({'power':'reveal','event_id':999})
        e=event(self.w.state,'scandal','Настоящий факт','factory','jobs','labor')
        self.w.intervene({'power':'reveal','event_id':e['id']});self.assertTrue(self.w.state['events'][-2]['revealed'])
    def test_unknown_news_no_magic_trust(self):
        c=self.w.state['cohorts'][0];before=dict(c['memory']);event(self.w.state,'promise_kept','Факт','factory','jobs','labor')
        self.assertEqual(c['memory'],before)
        self.w.step(4,False);self.assertGreater(self.w.state['cohorts'][0]['memory']['labor'],before['labor'])
    def test_meeting_builds_links(self):
        before=self.w.state['links']['factory']['outskirts'];self.w.intervene({'power':'meeting','target':'factory'})
        self.assertGreater(self.w.state['links']['factory']['outskirts'],before)
    def test_targeted_income_not_whole_city(self):
        other=World(seed=87);self.w.intervene({'power':'economy','target':'factory&worker','strength':20});self.w.step();other.step()
        self.assertEqual(self.w.state['districts']['center']['income'],other.state['districts']['center']['income'])
        self.assertGreater(self.w.state['districts']['factory']['income'],other.state['districts']['factory']['income'])
    def test_direct_twenty_points_and_clamp(self):
        c=self.w.state['cohorts'][0];before=attraction(self.w.state,c,'civic')[0]
        self.w.direct({'op':'popularity','party':'civic','target':c['id'],'value':20})
        after=attraction(self.w.state,self.w.state['cohorts'][0],'civic')[0];self.assertAlmostEqual(after,min(100,before+20))
        self.assertTrue(self.w.state['editor_used']);self.assertEqual(len(self.w.state['direct_log']),1)
    def test_dissolve_preserves_population(self):
        self.w.direct({'op':'dissolve','party':'labor'});self.assertNotIn('labor',forecast(self.w.state)['shares']);self.assertEqual(self.w.summary()['population'],24000)
    def test_last_party_cannot_dissolve(self):
        self.w.direct({'op':'dissolve','party':'labor'});self.w.direct({'op':'dissolve','party':'civic'})
        with self.assertRaises(RuleError):self.w.direct({'op':'dissolve','party':'order'})
    def test_create_party_and_vote(self):
        self.w.direct({'op':'create','name':'Новая партия','ideology':{a:0 for a in self.w.data['axes']}})
        self.assertIn('new1',forecast(self.w.state)['shares']);validate_state(self.w.state,self.w.data)
    def test_undo_whole_timeline(self):
        before=copy.deepcopy(self.w.state);self.w.direct({'op':'popularity','party':'labor','value':20});self.w.step(3,False);self.w.undo();self.assertEqual(self.w.state,before)
    def test_undo_bounded(self):
        for _ in range(5):self.w.direct({'op':'popularity','party':'labor','value':1})
        self.assertEqual(len(self.w.undo_buffer),3)
    def test_actor_succession_not_game_over(self):
        old=self.w.state['parties']['labor']['leader'];self.w.direct({'op':'retire','actor':old})
        new=self.w.state['parties']['labor']['leader'];self.assertNotEqual(old,new);self.assertTrue(self.w.state['actors'][new]['alive']);self.w.step()
    def test_platform_perception_not_omniscient(self):
        old=self.w.state['cohorts'][0]['perceived']['labor']['economy'];self.w.direct({'op':'ideology','party':'labor','axis':'economy','value':90})
        self.assertEqual(self.w.state['cohorts'][0]['perceived']['labor']['economy'],old)
        self.w.step(4,False);self.assertEqual(self.w.state['cohorts'][0]['perceived']['labor']['economy'],90)
    def test_invalid_direct_atomic(self):
        for cmd in ({'op':'popularity','party':'labor','value':float('nan')},{'op':'rules','key':'threshold','value':80},{'op':'resource','district':'center','field':'infra','value':101}):
            before=copy.deepcopy(self.w.state)
            with self.assertRaises(RuleError):self.w.direct(cmd)
            self.assertEqual(self.w.state,before)
    def test_saved_seed_and_continuation(self):
        self.w.step(8,False)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'мир.json';self.w.save(p);loaded=World(seed=4);loaded.load(p)
            self.w.step(6,False);loaded.step(6,False);self.assertEqual(self.w.state,loaded.state)
    def test_bad_save_does_not_change_current_world(self):
        before=copy.deepcopy(self.w.state)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'world.json';self.w.save(p);obj=json.loads(p.read_text(encoding="utf-8"));obj['payload']['state']['energy']=999
            p.write_text(json.dumps(obj),encoding="utf-8")
            with self.assertRaises(DataError):self.w.load(p)
        self.assertEqual(self.w.state,before)
    def test_corrupt_state_even_recomputed_checksum(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'world.json';self.w.save(p);obj=json.loads(p.read_text(encoding="utf-8"));obj['payload']['state']['cohorts'][0]['trust']['labor']='bad';obj['checksum']=fingerprint(obj['payload']);p.write_text(json.dumps(obj),encoding="utf-8")
            with self.assertRaises(DataError):self.w.load(p)
    def test_reject_candidate_save(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'old.json';p.write_text('{"schema_version":3}',encoding='utf-8')
            with self.assertRaises(DataError):self.w.load(p)
    def test_bounded_history_years(self):
        self.w.step(104,False);self.w.step(104,False);self.assertLessEqual(len(self.w.state['events']),600);self.assertLessEqual(len(self.w.state['polls']),24)

class GodLanguageTest(unittest.TestCase):
    def setUp(self):self.w=World(seed=87)
    def test_free_plan(self):
        p=parse(self.w,'Усилить внимание рабочих к экологии; затем улучшить транспорт в Заречье')
        self.assertTrue(p.ready,p.blocked);self.assertEqual(len(p.commands),2);before=self.w.state['energy'];execute(self.w,p);self.assertLess(self.w.state['energy'],before)
    def test_duration_not_strength(self):
        p=parse(self.w,'Вызвать мороз в Заречье на 3 недели');self.assertEqual(p.commands[0]['duration'],3);self.assertEqual(p.commands[0]['strength'],15)
    def test_explicit_strength_and_duration(self):
        p=parse(self.w,'Вызвать мороз сила 20 в Заречье на 3 недели');self.assertEqual(p.commands[0]['strength'],20)
    def test_conditions_not_discarded(self):
        for text in ('Усилить внимание к экологии если партия проиграет','Не буду вызывать мороз','Добавить 20% популярности партии','Распустить партию','Создать чёрную дыру','Вчера вызвал мороз','Он сказал: «Усилить внимание к экологии»'):
            p=parse(self.w,text);self.assertFalse(p.ready,text)
            with self.assertRaises(RuleError):execute(self.w,p)
    def test_no_partial_execution(self):
        p=parse(self.w,'Исцелить пенсионеров; затем создать чёрную дыру');before=copy.deepcopy(self.w.state)
        with self.assertRaises(RuleError):execute(self.w,p)
        self.assertEqual(self.w.state,before)
    def test_plan_tampering_blocked(self):
        p=parse(self.w,'Не буду вызывать мороз');p.blocked=[];p.commands=[{'power':'weather','target':'all','topic':'','strength':15,'duration':4}]
        with self.assertRaises(RuleError):execute(self.w,p)
    def test_composite_target(self):
        p=parse(self.w,'Благословить рабочих в Заводском районе достатком');self.assertEqual(p.commands[0]['target'],'factory&worker');self.assertTrue(p.ready)
    def test_reveal_requires_id(self):
        self.assertFalse(parse(self.w,'Раскрыть факт').ready)
        self.assertTrue(parse(self.w,'Раскрыть событие 1').ready)
    def test_bounds_and_ambiguity(self):
        for t in ('Наслать мороз сила 50','Наслать мороз на 20 недель','Усилить внимание к тарифам и экологии','Исцелить Центр и Заречье'):
            self.assertFalse(parse(self.w,t).ready,t)
    def test_neural_proposals_not_fiction(self):
        p=parse(self.w,'Создать чёрную дыру');self.assertFalse(p.ready);self.assertTrue(p.candidates)

    def test_reports_and_concessions_not_commands(self):
        for text in ('Он вызвал мороз', 'Партия улучшила транспорт', 'Усилить внимание к экологии, но не повышать явку'):
            self.assertFalse(parse(self.w,text).ready,text)


class GodNetworkTest(unittest.TestCase):
    def setUp(self):self.w=World(seed=87)
    def test_snapshot_roundtrip(self):
        other=World(seed=4);N.restore(other,N.snapshot(self.w));self.assertEqual(other.state,self.w.state)
    def test_host_validates_original_text(self):
        before=copy.deepcopy(self.w.state)
        with self.assertRaises(RuleError):N.command(self.w,0,'plan','Усилить внимание к экологии если партия проиграет')
        self.assertEqual(self.w.state,before)
    def test_guest_command_and_revision(self):
        N.command(self.w,0,'plan','Усилить внимание к экологии')
        with self.assertRaises(RuleError):N.command(self.w,0,'step',1)
        N.command(self.w,1,'step',1);self.assertEqual(self.w.state['week'],2)
    def test_no_arbitrary_operation(self):
        with self.assertRaises(RuleError):N.command(self.w,0,'eval',{'code':'evil'})
    def test_snapshot_shape_validated(self):
        for mutate in (lambda o:o.__setitem__('rules','bad'),lambda o:o['state']['cohorts'][0].__setitem__('population',-1)):
            obj=N.snapshot(self.w);mutate(obj)
            with self.assertRaises(DataError):N.restore(self.w,obj)

if __name__=='__main__':unittest.main()
