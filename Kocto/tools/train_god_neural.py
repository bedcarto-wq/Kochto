"""Run from Kocto: python tools/train_god_neural.py [--evaluate-only].
The god classifier suggests mechanisms, never invents effects or overrides guards.
"""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from gorod import neural,nlu
root=ROOT/'gorod'/'data'
parser=argparse.ArgumentParser();parser.add_argument('--evaluate-only',action='store_true');args=parser.parse_args()
data=json.loads((root/'god_world.json').read_text(encoding='utf-8'));corpus=json.loads((root/'god_phrases.json').read_text(encoding='utf-8'))
rows=neural.samples(corpus,list(data['powers']))
if args.evaluate_only:record=json.loads((root/'god_neural.json').read_text(encoding='utf-8'))
else:
 model=neural.train(rows,hidden=16,epochs=80,seed=8021,vocab_limit=1024);record=model.record()
 for k in ('w1','w2'):record[k]=[[round(v,7) for v in row] for row in record[k]]
 for k in ('b1','b2'):record[k]=[round(v,7) for v in record[k]]
 (root/'god_neural.json').write_text(json.dumps(record,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
model=neural.load(record,corpus,list(data['powers']));test=[p for p in corpus['phrases'] if p['split']=='test'];good=0
for p in test:
 scores=model.predict(nlu.tokens(p['text']));pred=max(scores,key=scores.get) if scores else None;good+=pred==p['action']
print(json.dumps({'train':len(rows),'test':len(test),'correct':good,'note':'Small synthetic check, not a general Russian understanding claim; proposals only.'},ensure_ascii=False))
