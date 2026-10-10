"""Reproducible whole-world benchmark. Run from Kocto: python tools/benchmark_world.py --weeks 26.
Measures rather than prescribing a language rewrite. No camera-dependent LOD.
"""
import argparse,json,sys,time,tracemalloc,tempfile,platform,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gorod.god.world import World,validate_state
from gorod.god import network

def main():
 p=argparse.ArgumentParser();p.add_argument('--weeks',type=int,default=26);p.add_argument('--output');a=p.parse_args()
 if not 1<=a.weeks<=104:p.error('weeks 1..104')
 result={'python':platform.python_version(),'seed':88,'weeks':a.weeks,'scales':{}}
 for scale in ('city','region','federation'):
  tracemalloc.start();start=time.perf_counter();w=World(seed=88,scale=scale);created=time.perf_counter()-start
  _,initial_peak=tracemalloc.get_traced_memory();tracemalloc.stop();start=time.perf_counter();w.step(a.weeks,False);elapsed=time.perf_counter()-start
  validate_state(w.state,w.data);packet=network.snapshot(w)
  sample=World();sample.data=w.data;sample.state=copy.deepcopy(w.state);tracemalloc.start();sample.step(1,False);_,week_peak=tracemalloc.get_traced_memory();tracemalloc.stop()
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'world.json';w.save(path);v=World();v.load(path);assert w.state==v.state
   size=path.stat().st_size
  result['scales'][scale]={'initialization_s':round(created,4),'initial_peak_allocated_bytes':initial_peak,'sample_week_peak_allocated_bytes':week_peak,'simulation_s':round(elapsed,4),'week_mean_s':round(elapsed/a.weeks,4),'save_bytes':size,'network_bytes':len(json.dumps(packet,ensure_ascii=False).encode()),'population':sum(c['population'] for city in __import__('gorod.god.territories',fromlist=['cities']).cities(w.state).values() for c in city['cohorts'])}
 text=json.dumps(result,ensure_ascii=False,indent=2)
 if a.output:Path(a.output).write_text(text,encoding='utf-8')
 else:print(text)
if __name__=='__main__':main()
