"""Independent upper branches and ballots; same residents, different known programmes.
Three common party identities, not three cloned municipal organizations.
Surveys are sampled/noisy; voter knowledge is distinct from authority truth.
"""
import copy,math,random
from ..engine import DataError

ACTIONS={'survey':'опрос','campaign':'кампания','organize':'развитие отделения'}
def clip(v,a=0,b=100):return max(a,min(b,v))
def levels(t):
    out={rid:[cid for cid,m in t['meta'].items() if m['region']==rid] for rid in sorted(t['regions'])}
    if t['scale']=='federation':out['federal']=sorted(t['meta'])
    return out

def initialize(s,data,seed_for,cities):
    t=s['territory']
    if not t:return
    if 'politics' in t:return
    t['politics']={};all_cities=cities(s)
    first=['Алексей','Елена','Сергей','Наталья','Андрей','Ольга','Дмитрий','Светлана','Артём'];last=['Волков','Лебедева','Соколов','Морозова','Власов','Романова','Громов','Кириллова','Крылов']
    for lid,members in levels(t).items():
        rng=random.Random(seed_for(t['seed'],'politics:'+lid));branches={}
        for i,(pid,party) in enumerate(sorted(data['parties'].items())):
            name_index=list(levels(t)).index(lid)*3+i
            leader={'id':lid+':'+pid+':leader','name':first[name_index%9]+' '+last[name_index%9],
                    'age':rng.randint(35,58),'alive':True,'honesty':rng.randint(35,90),'competence':rng.randint(35,85),'influence':rng.randint(35,80),'generation':0}
            branches[pid]={'ideology':dict(party['ideology']),'funds':60.0,'organization':30.0,'leader':leader,
                'intel':{'week':0,'sample':[],'means':{}},'decision':{'week':s['week'],'action':'organize','reason':'Начало работы отделения'}}
        voters={}
        for cid in sorted(members):
            for c in all_cities[cid]['cohorts']:
                voters[cid+'/'+c['id']]={pid:{'perceived':dict(p['ideology']),'familiarity':35.0,'trust':50.0,'known':[]} for pid,p in branches.items()}
        t['politics'][lid]={'branches':branches,'voters':voters,'facts':[],'next_fact':1}

def fact(level,week,pid,kind,text,cities,**fields):
    f={'id':level['next_fact'],'week':week,'party':pid,'kind':kind,'text':text,'cities':list(cities),**fields};level['next_fact']+=1;level['facts'].append(f);del level['facts'][:-80];return f

def aid(t,lid,recipient,amount,week):
    if lid not in t.get('politics',{}):return
    authority=t['federal'] if lid=='federal' else t['regions'][lid]
    if authority['government']:fact(t['politics'][lid],week,authority['government'][0],'transfer','Реальный перевод казны: '+str(round(amount,1)),([recipient] if recipient in t['meta'] else [cid for cid,m in t['meta'].items() if m['region']==recipient]),amount=amount)

def tick(s,data,cities,seed_for,record):
    t=s['territory'];week=s['week']-1;all_cities=cities(s)
    for lid,members in levels(t).items():
        level=t['politics'][lid];rng=random.Random(seed_for(t['seed'],'upper:'+lid+':'+str(week)))
        for pid,b in sorted(level['branches'].items()):
            actor=b['leader'];b['funds']=clip(b['funds']+.75,0,200)
            if week%52==0:
                actor['age']+=1
                if actor['age']>75:
                    actor.update(age=35+actor['generation']%15,generation=actor['generation']+1,competence=rng.randint(35,85),influence=rng.randint(30,75),honesty=rng.randint(35,90))
                    actor['id']=lid+':'+pid+':leader:'+str(actor['generation']);actor['name']='Преемник '+data['parties'][pid]['name']
                    fact(level,week,pid,'succession','Смена руководителя отделения',members)
            if week%4:continue
            intel=b['intel'];near=t['next_election']-week<=8
            if not intel['sample'] or week-intel['week']>=12:action='survey';cost=3
            elif near and b['funds']>=2:action='campaign';cost=2
            else:action='organize';cost=1
            if b['funds']<cost:b['decision']={'week':week,'action':'reserve','reason':'Недостаточно средств'};continue
            b['funds']-=cost;b['decision']={'week':week,'action':action,'reason':'Опрос устарел' if action=='survey' else 'Приближаются выборы' if action=='campaign' else 'Организационные ограничения между выборами'}
            if action=='survey':
                sample=[]
                for cid in sorted(members):
                    city=all_cities[cid];eligible=[c for c in city['cohorts'] if c['population']]
                    for c in rng.sample(eligible,min(6,len(eligible))):
                        sample.append({'city':cid,'cohort':c['id'],'opinions':{a:clip(c['ideology'][a]+rng.gauss(0,11),-100,100) for a in data['axes']}})
                means={a:sum(r['opinions'][a] for r in sample)/max(1,len(sample)) for a in data['axes']}
                b['intel']={'week':week,'sample':sample,'means':means};fact(level,week,pid,'survey','Шумный опрос: '+str(len(sample))+' наблюдений, не весь электорат',members)
            elif action=='campaign':
                axis=max(data['axes'],key=lambda a:abs(intel['means'].get(a,0)-b['ideology'][a]))
                b['ideology'][axis]=clip(b['ideology'][axis]+.04*(intel['means'][axis]-b['ideology'][axis]),-100,100)
                fact(level,week,pid,'campaign','Кампания отделения; публичная программа может стать известной',members,ideology=dict(b['ideology']))
            else:b['organization']=clip(b['organization']+actor['competence']/100)
        # Information diffuses with limited reach. Transfer is awareness, not a popularity grant.
        for cid in sorted(members):
            city=all_cities[cid]
            for c in city['cohorts']:
                knowledge=level['voters'][cid+'/'+c['id']]
                for f in level['facts'][-20:]:
                    if week-f['week']>8 or f['kind'] not in ('campaign','transfer') or f['id'] in knowledge[f['party']]['known']:continue
                    k=knowledge[f['party']];local=cid in f['cities']
                    chance=(.10 if local else .025)*(.5+c['engagement']/100)*(city['media_trust']['paper']/65)
                    if rng.random()<chance:
                        k['known'].append(f['id']);del k['known'][:-24]
                        if f['kind']=='campaign':k['perceived']=dict(f['ideology']);k['familiarity']=clip(k['familiarity']+1.5+level['branches'][f['party']]['organization']/50)
                        else:k['familiarity']=clip(k['familiarity']+.3)
                # Real observed local service experience informs the responsible regional tier.
                if lid!='federal':
                    authority=t['regions'][lid]
                    for pid in authority['government']:
                        known_aid=any(f['party']==pid and f['kind']=='transfer' and cid in f['cities'] and f['id'] in knowledge[pid]['known'] and week-f['week']<=8 for f in level['facts'])
                        if known_aid:
                            # No claim to exact attribution: recipients judge experience after known aid.
                            knowledge[pid]['trust']=clip(knowledge[pid]['trust']+(.03 if c['service_pressure']<3 else -.015))

def choice(t,lid,cid,city,c):
    level=t['politics'][lid];perception=level['voters'][cid+'/'+c['id']];scores={}
    for pid,b in level['branches'].items():
        k=perception[pid];weights=c['weights'];total=sum(weights.values())
        ideology=100*(1-sum(weights[a]*abs(c['ideology'][a]-k['perceived'][a]) for a in weights)/(200*total))
        recognized=k['familiarity']/100;leader=b['leader']
        scores[pid]=clip(ideology+(k['trust']-50)*.2+(k['familiarity']-35)*.08+(leader['influence']-50)*.08*recognized)
    peak=max(scores.values());raw={p:math.exp((v-peak)/14) for p,v in scores.items()};den=sum(raw.values());probs={p:v/den for p,v in raw.items()}
    access=city['districts'][c['district']]['access'];turnout=clip(.25+c['engagement']*.003+peak*.002+access*.0015-c['stress']*.001+c['turnout_bias']*.01,.05,.95)
    return probs,turnout

def policy_data(t,lid,data):
    out={'parties':{pid:{**p,'ideology':dict(t['politics'][lid]['branches'][pid]['ideology'])} for pid,p in data['parties'].items()}}
    return out

def validate(s,data,cities):
    t=s['territory']
    if not t:return
    if set(t['politics'])!=set(levels(t)):raise DataError('upper politics: levels')
    all_cities=cities(s)
    def number(v,low,high):
        if type(v) not in (int,float) or not math.isfinite(v) or not low<=v<=high:raise DataError('upper politics: number')
    for lid,members in levels(t).items():
        level=t['politics'][lid];expected_voters={cid+'/'+c['id'] for cid in members for c in all_cities[cid]['cohorts']}
        if set(level)!={'branches','voters','facts','next_fact'} or set(level['branches'])!=set(data['parties']) or set(level['voters'])!=expected_voters or len(level['facts'])>80 or type(level['next_fact']) is not int or level['next_fact']<1:raise DataError('upper politics: schema')
        for pid,b in level['branches'].items():
            if set(b)!={'ideology','funds','organization','leader','intel','decision'} or set(b['ideology'])!=set(data['axes']):raise DataError('upper politics: branch')
            number(b['funds'],0,200);number(b['organization'],0,100)
            for v in b['ideology'].values():number(v,-100,100)
            a=b['leader']
            if set(a)!={'id','name','age','alive','honesty','competence','influence','generation'} or not isinstance(a['name'],str) or not 1<=len(a['name'])<=80 or not isinstance(a['id'],str) or not a['id'].startswith(lid+':'+pid+':') or type(a['alive']) is not bool or type(a['age']) is not int or not 18<=a['age']<=120 or type(a['generation']) is not int or a['generation']<0:raise DataError('upper politics: actor')
            for k in ('honesty','competence','influence'):number(a[k],0,100)
            intel=b['intel']
            if set(intel)!={'week','sample','means'} or set(intel['means']) not in (set(),set(data['axes'])) or len(intel['sample'])>24 or type(intel['week']) is not int or not 0<=intel['week']<=s['week'] or b['decision']['action'] not in ('survey','campaign','organize','reserve'):raise DataError('upper politics: intel')
            for v in intel['means'].values():number(v,-100,100)
            if set(b['decision'])!={'week','action','reason'} or type(b['decision']['week']) is not int or not 1<=b['decision']['week']<=s['week'] or not isinstance(b['decision']['reason'],str):raise DataError('upper politics: decision')
            for row in intel['sample']:
                if set(row)!={'city','cohort','opinions'} or row['city'] not in members or row['cohort'] not in {c['id'] for c in all_cities[row['city']]['cohorts']} or set(row['opinions'])!=set(data['axes']):raise DataError('upper politics: sample')
                for v in row['opinions'].values():number(v,-100,100)
        for perceptions in level['voters'].values():
            if set(perceptions)!=set(data['parties']):raise DataError('upper politics: voter')
            for k in perceptions.values():
                if set(k)!={'perceived','familiarity','trust','known'} or set(k['perceived'])!=set(data['axes']) or len(k['known'])>24 or any(type(i) is not int or not 0<i<level['next_fact'] for i in k['known']):raise DataError('upper politics: knowledge')
                number(k['trust'],0,100);number(k['familiarity'],0,100)
                for v in k['perceived'].values():number(v,-100,100)
        ids=set()
        for f in level['facts']:
            if type(f['id']) is not int or f['id'] in ids or not 0<f['id']<level['next_fact'] or type(f['week']) is not int or not 1<=f['week']<=s['week'] or f['party'] not in data['parties'] or any(cid not in t['meta'] for cid in f['cities']):raise DataError('upper politics: facts')
            fields={'id','week','party','kind','text','cities'}
            if f['kind']=='campaign':
                fields.add('ideology')
                if set(f['ideology'])!=set(data['axes']):raise DataError('upper politics: campaign')
                for v in f['ideology'].values():number(v,-100,100)
            elif f['kind']=='transfer':fields.add('amount');number(f['amount'],0,300)
            elif f['kind'] not in ('survey','succession'):raise DataError('upper politics: fact kind')
            if set(f)!=fields or not isinstance(f['text'],str) or len(f['text'])>500:raise DataError('upper politics: fact schema')
            ids.add(f['id'])

def forecast(t,lid,cities):
    totals={p:0.0 for p in t['politics'][lid]['branches']};population=0
    for cid in levels(t)[lid]:
        city=cities[cid]
        for c in city['cohorts']:
            probs,turnout=choice(t,lid,cid,city,c);population+=c['population']
            for pid,prob in probs.items():totals[pid]+=c['population']*turnout*prob
    total=sum(totals.values());return {p:100*v/max(1,total) for p,v in totals.items()},total/max(1,population)*100
