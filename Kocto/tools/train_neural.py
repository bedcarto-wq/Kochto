"""Run from Kocto: python tools/train_neural.py. Offline, stdlib only."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gorod import neural, nlu
ROOT = Path(__file__).resolve().parents[1]/'gorod'/'data'
parser=argparse.ArgumentParser()
parser.add_argument('--epochs',type=int,default=100)
parser.add_argument('--evaluate-only',action='store_true')
args=parser.parse_args()
if not 1 <= args.epochs <= 2000: parser.error("epochs must be 1..2000")
corpus=json.loads((ROOT/'train_phrases.json').read_text(encoding='utf-8'))
actions=list(json.loads((ROOT/'gorod_mvp.json').read_text(encoding='utf-8'))['actions'])
rows=neural.samples(corpus,actions)
if args.evaluate_only:
 record=json.loads((ROOT/'neural_model.json').read_text(encoding='utf-8'))
else:
 model=neural.train(rows,epochs=args.epochs)
 record=model.record()
 for key in ('w1','w2'):record[key]=[[round(v,7) for v in row] for row in record[key]]
 for key in ('b1','b2'):record[key]=[round(v,7) for v in record[key]]
 (ROOT/'neural_model.json').write_text(json.dumps(record,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
model=neural.load(record,corpus,actions)
test=[p for p in corpus['phrases'] if p['split']=='test']
correct=0;miss=[]
for p in test:
 probs=model.predict(nlu.tokens(p['text']));pred=max(probs,key=probs.get) if probs else None
 correct+=pred==p['action']
 if pred!=p['action']:miss.append({'text':p['text'],'expected':p['action'],'predicted':pred})
report={'train_examples':len(rows),'test_examples':len(test),'correct':correct,'accuracy':correct/len(test),'epochs':args.epochs,'seed':751,'vocab':len(model.vocab),'hidden':model.hidden,'train_digest':model.train_digest,'mistakes':miss}
check_path=ROOT/'neural_check.json'
if check_path.exists():
 check=json.loads(check_path.read_text(encoding='utf-8'))['phrases']
 good=0;errors=[]
 for row in check:
  probs=model.predict(nlu.tokens(row['text']));pred=max(probs,key=probs.get) if probs else None
  good+=pred==row['action']
  if pred!=row['action']:errors.append({'text':row['text'],'expected':row['action'],'predicted':pred})
 report['independent_check']={'examples':len(check),'correct':good,'accuracy':good/len(check),'mistakes':errors}
report['model_digest']=neural.digest(record)
(ROOT/'neural_metrics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
