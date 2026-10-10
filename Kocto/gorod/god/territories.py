"""Small fully simulated hierarchy. Camera does not schedule computation.
Local IDs are scoped by stable city IDs. Higher elections aggregate local cohort preferences.
"""
import copy,hashlib
from ..engine import DataError,RuleError
SCALES={'city':'Город','region':'Регион','federation':'Федерация'}

def seed_for(seed,cid):return int.from_bytes(hashlib.sha256((str(seed)+':'+cid).encode()).digest()[:8],'big')
def local(s):
    c=copy.deepcopy(s);c['territory']=None;return c

def cities(s):
    t=s['territory']
    return {t['active']:s,**t['cities']} if t else {'r0:c0':s}

def initialize(s,data,scale,new_state):
    if scale not in SCALES:raise RuleError('Неизвестный масштаб')
    if scale=='city':return
    count=2 if scale=='region' else 4
    meta={};saved={}
    for i in range(count):
        cid='r'+str(i//2)+':c'+str(i%2);spec=data['scale_rules']['cities'][i];meta[cid]={'name':spec['name'],'region':'r'+str(i//2)}
        if i:
            local_data=copy.deepcopy(data)
            for district in local_data['districts'].values():
                for field in ('income','jobs','infra'):district[field]=max(0,min(100,district[field]+spec[field]))
            child=new_state(local_data,seed_for(s['seed'],cid));child['territory']=None;saved[cid]=child
    regions={rid:{'name':['Речной регион','Северный регион'][int(rid[1:])],'budget':60.0,'government':[],'elections':[]} for rid in {v['region'] for v in meta.values()}}
    ids=sorted(meta);links={a:{b:(.7 if meta[a]['region']==meta[b]['region'] else .2) for b in ids if b!=a} for a in ids}
    s['territory']={'seed':s['seed'],'scale':scale,'active':'r0:c0','meta':meta,'cities':saved,'regions':regions,'federal':{'budget':90.0,'government':[],'elections':[]},'links':links,'events':[],'next_event':1,'next_election':12}

def record(t,week,text,refs=None):
    t['events'].append({'id':t['next_event'],'week':week,'text':text,'cities':list(refs or [])});t['next_event']+=1;del t['events'][:-180]

def select(s,cid):
    t=s['territory']
    if not t or cid not in t['meta']:raise RuleError('Нет такой территории')
    if cid==t['active']:return
    old=t['active'];energy=s['energy'];revision=s['revision'];t['cities'][old]=local(s);chosen=t['cities'].pop(cid);t['active']=cid
    s.clear();s.update(chosen);s['territory']=t;s['energy']=energy;s['revision']=revision+1

def priority(city,pid,data):
    ideology=data['parties'][pid]['ideology'];jobs=sum(d['jobs'] for d in city['districts'].values())/4
    pollution=sum(d['pollution'] for d in city['districts'].values())/4;income=sum(d['income'] for d in city['districts'].values())/4
    pressure=sum(c['material'] for c in city['crises']['items'] if c['stage']!='resolved')
    # Left governments weigh need/job losses; market governments weigh economic capacity.
    return pressure+(100-ideology['economy'])/100*max(0,70-jobs)+max(0,ideology['economy'])/100*income+max(0,ideology['ecology'])/100*pollution

def step(s,data,advance,choice,allocate,event):
    t=s['territory'];week=s['week'];revision=s['revision'];root_report=None
    # Independent stored streams and canonical order, irrespective of selected city.
    all_cities=cities(s)
    for cid in sorted(all_cities):
        report=advance(all_cities[cid],data)
        if cid==t['active']:root_report=report
    # Links transmit pressure through actual economic dependence, not global penalties.
    before={cid:sum(d['jobs'] for d in c['districts'].values())/4 for cid,c in all_cities.items()}
    for cid,c in all_cities.items():
        impulse=sum(t['links'][cid][other]*(before[other]-50) for other in t['links'][cid])*.003
        # Actual service interruptions and labour actions constrain connected supply.
        supply=sum(t['links'][cid][other]*(1-sum(f.get('output',1) for f in all_cities[other]['firms'].values())/4) for other in t['links'][cid])
        impulse-=supply*.4
        if supply>.01 and week%4==0:record(t,week,t['meta'][cid]['name']+': поставки ограничены трудовым конфликтом связанного города',[cid])
        for d in c['districts'].values():d['income']=max(0,min(100,d['income']+impulse))
    # Periodic intercity migration uses existing cohorts and conserves residents and stocks.
    if week%13==0:
        from . import living
        poorest=min(all_cities,key=lambda k:(before[k],k));richest=max(all_cities,key=lambda k:(before[k],k))
        if poorest!=richest and t['links'][poorest][richest]>0:
            src=all_cities[poorest];dst=all_cities[richest];a=next((c for c in src['cohorts'] if 'worker' in c['tags'] and c['population']>20),None)
            if a:
                b=next(c for c in dst['cohorts'] if set(c['tags'])==set(a['tags']));n=min(3,a['population']);living.transfer_mean(a,b,n);a['population']-=n;b['population']+=n
                for city in (src,dst):
                    for did,d in city['districts'].items():d['population']=sum(c['population'] for c in city['cohorts'] if c['district']==did)
                record(t,week,str(n)+' жителей переехали из '+t['meta'][poorest]['name']+' в '+t['meta'][richest]['name'],[poorest,richest])
    # Governments allocate real treasury balances to needy cities. Transfer is conserved.
    for rid,r in sorted(t['regions'].items()):
        r['budget']=min(300,r['budget']+4)
        members=[k for k,v in t['meta'].items() if v['region']==rid]
        if week%4==0 and r['government'] and r['budget']>=12:
            need=max(members,key=lambda k:(priority(all_cities[k],r['government'][0],data),k))
            city=all_cities[need];amount=min(12,300-city['budget'])
            if amount>0:r['budget']-=amount;city['budget']+=amount;record(t,week,r['name']+' перечисляет '+str(round(amount,1))+' городу '+t['meta'][need]['name'],[need]);event(city,'regional_aid','Получено из регионального бюджета: '+str(round(amount,1)))
    federal=t['federal']
    if t['scale']=='federation':
        federal['budget']=min(300,federal['budget']+5)
        if week%8==0 and federal['government'] and federal['budget']>=16:
            rid=max(t['regions'],key=lambda rid:sum(priority(all_cities[cid],federal['government'][0],data) for cid,m in t['meta'].items() if m['region']==rid)-t['regions'][rid]['budget']*.2);r=t['regions'][rid];amount=min(16,300-r['budget']);federal['budget']-=amount;r['budget']+=amount;record(t,week,'Федерация перечисляет '+str(round(amount,1))+' региону '+r['name'])
    if week>=t['next_election']:
        levels=[(rid,r,[k for k,v in t['meta'].items() if v['region']==rid]) for rid,r in sorted(t['regions'].items())]
        if t['scale']=='federation':levels.append(('federal',federal,sorted(all_cities)))
        for lid,authority,members in levels:
            votes={p:0 for p in data['parties']}
            for cid in members:
                c=all_cities[cid]
                for cohort in c['cohorts']:
                    probs,turnout=choice(c,cohort)
                    eligible={pid:value for pid,value in probs.items() if pid in votes};total=sum(eligible.values());n=round(cohort['population']*turnout) if total else 0
                    raw={pid:n*value/total for pid,value in eligible.items()} if total else {};counts={pid:int(value) for pid,value in raw.items()}
                    for pid in sorted(raw,key=lambda p:(-(raw[p]-counts[p]),p))[:n-sum(counts.values())]:counts[pid]+=1
                    for pid,value in counts.items():votes[pid]+=value
            seats=allocate(votes,15,5);ordered=sorted(seats,key=lambda p:(-seats[p],p));gov=[];total=0
            for pid in ordered:
                if seats[pid]>0:gov.append(pid);total+=seats[pid]
                if total>=8:break
            authority['government']=gov;authority['elections'].append({'week':week,'votes':votes,'seats':seats});del authority['elections'][:-20]
            record(t,week,('Федеральные' if lid=='federal' else authority['name']+': региональные')+' выборы; власть: '+', '.join(data['parties'][p]['name'] for p in gov),members)
        t['next_election']=week+26
    s['revision']=revision+1
    return root_report

def validate(s,data,validate_city):
    t=s['territory']
    if t is None:return
    expected={'seed','scale','active','meta','cities','regions','federal','links','events','next_event','next_election'}
    if type(t['seed']) is not int or not 0<=t['seed']<2**64 or set(t)!=expected or t['scale'] not in ('region','federation') or len(t['meta'])!=(2 if t['scale']=='region' else 4) or t['active'] not in t['meta'] or set(t['cities'])!=set(t['meta'])-{t['active']}:raise DataError('territory: schema')
    ids={'r0:c0','r0:c1'} if t['scale']=='region' else {'r0:c0','r0:c1','r1:c0','r1:c1'}
    regions={'r0'} if t['scale']=='region' else {'r0','r1'}
    if set(t['meta'])!=ids or set(t['links'])!=ids or set(t['regions'])!=regions:raise DataError('territory: references')
    for cid,c in t['cities'].items():
        if c['territory'] is not None or c['week']!=s['week']:raise DataError('territory: nested or unsynchronized city')
        validate_city(c,data)
    for cid,m in t['meta'].items():
        if set(m)!={'name','region'} or m['region']!=cid.split(':')[0] or m['region'] not in t['regions'] or not isinstance(m['name'],str) or not 1<=len(m['name'])<=60:raise DataError('territory: metadata')
    for cid,links in t['links'].items():
        if cid not in t['meta'] or set(links)!=set(t['meta'])-{cid} or any(type(v) not in (int,float) or not 0<=v<=1 for v in links.values()):raise DataError('territory: links')
    for r in [*t['regions'].values(),t['federal']]:
        if type(r['budget']) not in (int,float) or not 0<=r['budget']<=300 or len(r['elections'])>20 or any(p not in data['parties'] for p in r['government']):raise DataError('territory: authority')
    for r in [*t['regions'].values(),t['federal']]:
        for e in r['elections']:
            if set(e)!={'week','votes','seats'} or type(e['week']) is not int or not 1<=e['week']<=s['week'] or set(e['votes'])!=set(data['parties']) or set(e['seats'])!=set(data['parties']) or any(type(v) is not int or v<0 for v in [*e['votes'].values(),*e['seats'].values()]):raise DataError('territory: election')
    for e in t['events']:
        if set(e)!={'id','week','text','cities'} or type(e['id']) is not int or not 0<e['id']<t['next_event'] or type(e['week']) is not int or not 1<=e['week']<=s['week'] or not isinstance(e['text'],str) or any(cid not in ids for cid in e['cities']):raise DataError('territory: event')
    if len(t['events'])>180 or type(t['next_event']) is not int or t['next_event']<1 or type(t['next_election']) is not int or t['next_election']<1:raise DataError('territory: chronology')
