import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from gorod import engine as E, neural as N, nlu, parser as P
from gorod.session import Session
from gorod.multiplayer import Match, candidate, LEGACY_070
from gorod.shortcuts import ShortcutStore, normalize_clipboard, LIMIT

SK={'charm':30,'eloquence':30,'cunning':30}

class NeuralTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=E.load_data();cls.corpus=E.load_json(E.DATA_DIR/'train_phrases.json');cls.record=E.load_json(E.DATA_DIR/'neural_model.json')
    def test_real_mlp_loaded(self):
        m=self.data['_nlu'];self.assertIsInstance(m,N.NeuralClassifier)
        self.assertEqual(m.hidden,24);self.assertEqual(len(m.w2),len(self.data['actions']))
    def test_training_digest_excludes_checks(self):
        rows=N.samples(self.corpus,list(self.data['actions']))
        self.assertEqual(N.digest(rows),self.record['train_digest'])
        altered=copy.deepcopy(self.corpus)
        for p in altered['phrases']:
            if p['split']=='test':p['text']='отдельная контрольная фраза'
        self.assertEqual(N.digest(N.samples(altered,list(self.data['actions']))),N.digest(rows))
    def test_independent_check_set(self):
        checks=E.load_json(E.DATA_DIR/'neural_check.json')['phrases']
        train={t for t,_ in N.samples(self.corpus,list(self.data['actions']))}
        self.assertFalse(train & {p['text'] for p in checks})
        good=0
        for p in checks:
            scores=self.data['_nlu'].predict(nlu.tokens(p['text']))
            good+=bool(scores) and max(scores,key=scores.get)==p['action']
        self.assertGreaterEqual(good/len(checks),.85)
    def test_softmax_and_unknown_evidence(self):
        m=self.data['_nlu'];p=m.predict(nlu.tokens('посидеть с бабушками на лавочке'))
        self.assertAlmostEqual(sum(p.values()),1);self.assertEqual(max(p,key=p.get),'meeting')
        self.assertIsNone(m.predict(nlu.tokens('123 я и')))
        self.assertFalse(m.supported(nlu.tokens('съесть пиццу на луне')))
        self.assertIsNone(P.parse(self.data,'съесть пиццу на луне').card)
    def test_deterministic_training(self):
        rows=[('встретиться с рабочими','meeting'),('нанять охрану','security')]*2
        a=N.train(rows,hidden=4,epochs=5,vocab_limit=30).record()
        b=N.train(rows,hidden=4,epochs=5,vocab_limit=30).record()
        self.assertEqual(a,b)
    def test_base_weights_unchanged_by_learning(self):
        m=self.data['_nlu'];before=copy.deepcopy(m.record())
        adapted=m.extended([('созвать пикет у мэрии','publicize')]*3,2)
        self.assertNotEqual(adapted.w2,m.w2);self.assertEqual(m.record(),before)
    def test_model_corruption_is_explicit(self):
        for mutate in (lambda r:r['w1'][0].pop(),lambda r:r['w2'][0].__setitem__(0,float('nan')),
                       lambda r:r.__setitem__('labels',['security']),lambda r:r.__setitem__('train_digest','broken'),
                       lambda r:r.__setitem__('hidden',True),lambda r:r['b1'].__setitem__(0,True)):
            r=copy.deepcopy(self.record);mutate(r)
            with self.assertRaises(E.DataError):N.load(r,self.corpus,list(self.data['actions']))
    def test_missing_model_does_not_silently_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            dest=Path(temp)
            for name in ('gorod_mvp.json','press.json','intents.json','train_phrases.json'):
                (dest/name).write_bytes((E.DATA_DIR/name).read_bytes())
            with self.assertRaises(E.DataError):E.load_data(dest)
    def test_language_guards_survive_neural_classifier(self):
        s=Session(self.data);s.new('Анна','f',SK,seed=2)
        for text in ('Не буду нанимать охрану','Ложкин сказал: «Обещаю заморозить тарифы»','Как лучше встретиться с рабочими?',
                     'Поддержу завод если директор поставит фильтры'):
            before=E.to_dict(s.state);self.assertFalse(s.understand(text)['ready'])
            with self.assertRaises(E.RuleError):s.confirm()
            self.assertEqual(before,E.to_dict(s.state))
    def test_explanation_contains_neural_candidates(self):
        s=Session(self.data);s.new('Анна','f',SK,seed=2);s.understand('посидеть с бабушками на лавочке')
        ev=[x for x in s.intent.steps[0].evidence if x['field']=='classifier'][0]
        self.assertEqual(ev['candidates'][0]['action'],'meeting');self.assertEqual(len(ev['candidates']),3)
    def test_accept_synonym_uses_context_not_neural_guess(self):
        s=Session(self.data);s.new('Анна','f',SK,seed=2)
        s.understand('Переговоры с председателем за заморозку тарифов')
        with patch.object(E,'_roll',return_value={'tier':'success','roll':80,'total':90,'difficulty':40}):s.confirm()
        for phrase in ('Соглашаюсь на договор с председателем','Принимаю предложенные председателем условия','Принять условия председателя'):
            v=s.understand(phrase);self.assertEqual(v['action'],'accept_deal');self.assertTrue(v['ready'],v)
    def test_report_matches_packaged_weights(self):
        report=E.load_json(E.DATA_DIR/'neural_metrics.json')
        self.assertEqual(report['model_digest'],N.digest(self.record))
    def test_070_match_migration(self):
        m=Match(self.data,[candidate('Анна','f',SK),candidate('Борис','m',SK)],seed=3)
        old=m.snapshot();old['rules']=LEGACY_070
        restored=Match.restore(self.data,old)
        self.assertNotEqual(restored.snapshot()['rules'],LEGACY_070)
        old['rules']='not-an-approved-hash'
        with self.assertRaises(E.DataError):Match.restore(self.data,old)

class ShortcutTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'gorod_saves'/'my_actions.json'
        self.store=ShortcutStore(self.path)
    def tearDown(self):self.temp.cleanup()
    def test_create_restart_edit_delete(self):
        x=self.store.put('Штаб','Встретиться с рабочими; затем нанять охрану')
        other=ShortcutStore(self.path);self.assertEqual(other.items,[x])
        other.put('Встреча','Встретиться с пенсионерами',x['id'])
        self.assertEqual(ShortcutStore(self.path).items[0]['name'],'Встреча')
        other.delete(x['id']);self.assertEqual(ShortcutStore(self.path).items,[])
    def test_name_text_and_limits(self):
        self.store.put('Штаб','нанять охрану')
        for name,text in [('штаб','нанять охрану'),('','нанять охрану'),('А'*33,'нанять охрану'),('Слово',''),('Слово','х'*2001)]:
            with self.assertRaises(E.DataError):self.store.put(name,text)
        for i in range(LIMIT-1):self.store.put(str(i),'нанять охрану')
        with self.assertRaises(E.DataError):self.store.put('Лишнее','нанять охрану')
    def test_atomic_failed_write_preserves_old_file(self):
        self.store.put('Штаб','нанять охрану');before=self.path.read_bytes()
        with patch('gorod.shortcuts.os.replace',side_effect=PermissionError('read-only')):
            with self.assertRaises(E.DataError):self.store.put('Встреча','встретиться с рабочими')
        self.assertEqual(self.path.read_bytes(),before);self.assertEqual(len(self.store.items),1)
    def test_corrupt_preferences_preserved(self):
        self.path.parent.mkdir();self.path.write_text('broken',encoding='utf-8')
        store=ShortcutStore(self.path);self.assertTrue(store.load_error)
        with self.assertRaises(E.DataError):store.put('Штаб','нанять охрану')
        self.assertEqual(self.path.read_text(),'broken')
    def test_no_code_execution_format(self):
        self.path.parent.mkdir();self.path.write_text(json.dumps({'schema':1,'items':[{'id':'a'*32,'name':'x','text':'нанять охрану','code':'evil'}]}))
        self.assertTrue(ShortcutStore(self.path).load_error)
    def test_presets_still_go_through_guards(self):
        x=self.store.put('Условие','Поддержу завод если директор поставит фильтры')
        s=Session();s.new('Анна','f',SK,seed=1)
        self.assertFalse(s.understand(x['text'])['ready'])
    def test_missing_delete_not_noop(self):
        with self.assertRaises(E.DataError):self.store.delete('b'*32)
    def test_clipboard_multiline(self):
        self.assertEqual(normalize_clipboard('  Встретиться с рабочими\r\n\nнанять\tохрану  '),'Встретиться с рабочими; нанять охрану')
        self.assertEqual(normalize_clipboard('Поддержу завод если директор поставит фильтры'),'Поддержу завод если директор поставит фильтры')
    def test_clipboard_invalid(self):
        for text in ('','\n\t','a\x00b','x'*2001,None):
            with self.assertRaises(E.RuleError):normalize_clipboard(text)

if __name__=='__main__':unittest.main()
