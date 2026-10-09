"""Bounded utility planner, using sampled observations rather than exact preferences.
This is transparent decision AI, not a claim of a general neural agent.
"""
from __future__ import annotations
import math
from ..engine import DataError

NAMES={'campaign':'Агитация','mobilize':'Мобилизация','organize':'Развитие организации','promise':'Дать обещание','listen':'Выслушать жителей','fundraise':'Собрать средства','rest':'Сохранить ресурсы'}
COST={'campaign':8,'mobilize':6,'organize':10,'promise':2,'listen':3,'fundraise':0,'rest':0}
def clip(x,a=0,b=100):return max(a,min(b,x))

def initialize(s):
    for a in s['actors'].values():
        if 'decision' not in a:a['decision']={'week':0,'action':'rest','target':'','topic':'','reason':'Решение ещё не принято','options':[],'event':0}
    for p in s['parties'].values():
        if 'intel' not in p:p['intel']={'week':0,'sample':0,'districts':{},'share':0.0,'public_axes':{}}
        if 'intent' not in p:p['intent']={'action':'listen','until':0}

def survey(s,data,pid,rng):
    """A small imperfect sample. RNG and observations are persisted in state."""
    from .world import attraction
    rows={};axes={a:[] for a in data['axes']};sample_count=0
    for did in s['districts']:
        local=[c for c in s['cohorts'] if c['district']==did and c['population']]
        if not local:continue
        sample=rng.choices(local,weights=[c['population'] for c in local],k=6);sample_count+=len(sample)
        row={'support':clip(sum(attraction(s,c,pid)[0] for c in sample)/len(sample)+rng.gauss(0,6)),
             'hardship':clip(sum(100-c['household']['security'] for c in sample)/len(sample)+rng.gauss(0,7)),
             'jobs':clip(s['districts'][did]['jobs']+rng.gauss(0,8)),
             'infra':clip(s['districts'][did]['infra']+rng.gauss(0,8)),
             'attention':{t:clip(sum(c['attention'][t] for c in sample)/len(sample)+rng.gauss(0,5)) for t in data['topics']}}
        rows[did]=row
        for a in axes:axes[a].extend(c['ideology'][a] for c in sample)
    public=s['polls'][-1]['shares'].get(pid,0) if s['polls'] else 100/max(1,sum(p['active'] for p in s['parties'].values()))
    return {'week':s['week'],'sample':sample_count,'districts':rows,'share':public,'public_axes':{a:clip(sum(v)/max(1,len(v))+rng.gauss(0,8),-100,100) for a,v in axes.items()}}

def choose(s,data,pid):
    p=s['parties'][pid];a=s['actors'][p['leader']];intel=p['intel'];rows=[]
    observations=intel['districts']
    if not observations:return {'action':'rest','target':'','topic':'','score':0.0,'reason':'Нет наблюдений жителей'},[]
    targets=[]
    for did,r in observations.items():
        topic=max(r['attention'],key=lambda t:(r['attention'][t],t));key=did+':'+topic
        score=r['attention'][topic]+(100-r['support'])*.18-p['fatigue'].get(key,0)*4
        targets.append((score,did,topic))
    _,did,topic=max(targets);r=observations[did]
    deadline=max(0,s['rules'].get('next_election',s['rules']['first_election'])-s['week'])
    nearing=1-deadline/max(1,s['rules']['election_period']);open_count=sum(x['party']==pid and x['status']=='open' for x in s['promises'])
    def add(action,score,why,target=did,t=topic):
        if p['funds']>=COST[action]:rows.append({'action':action,'target':target,'topic':t,'score':round(score,4),'reason':why})
    add('campaign',30+nearing*15+r['attention'][topic]*.2-p['fatigue'].get(did+':'+topic,0)*5,'Спрос на тему в выборке; повторение агитации снижает полезность')
    add('mobilize',15+nearing*25+r['support']*.22-(100-p['organization'])*.12,'Знакомая аудитория и близость выборов; привлекаются сторонники, а не все жители')
    add('organize',28+(100-p['organization'])*.32-nearing*12,'Слабая организация; долгосрочное представительство важнее немедленных голосов')
    if open_count<2:
        t='services' if r['infra']<r['jobs'] else 'jobs'
        honesty_penalty=(a['honesty']/100)*(20 if pid not in s['governing'] else 8)
        add('promise',25+r['hardship']*.35+a['risk']*.15-open_count*15-honesty_penalty,'Материальная нужда из выборки; честность и уже взятые обязательства ограничивают обещания',did,t)
    age=s['week']-intel['week']
    add('listen',20+age*4+a['honesty']*.12,'Сведения устарели; опрос стоит денег и откладывает агитацию')
    add('fundraise',8+(60-p['funds'])*.9,'Без средств нельзя оплатить кампанию или организацию')
    add('rest',5+a['honesty']*.04,'Не тратить ресурсы без достаточной причины')
    # Character and relationships do not bypass the affordability/knowledge checks.
    chosen=max(rows,key=lambda x:(x['score'],x['action']))
    return chosen,sorted(rows,key=lambda x:(-x['score'],x['action']))

def perform(s,data,pid,choice,rng,emit):
    p=s['parties'][pid];a=s['actors'][p['leader']];action=choice['action'];did=choice['target'];t=choice['topic']
    p['funds']-=COST[action];e=None
    if action=='campaign':
        key=did+':'+t;fatigue=p['fatigue'].get(key,0);p['fatigue'][key]=fatigue+1
        e=emit(s,'campaign',p['name']+' обсуждает '+data['topics'][t]['name'].lower()+' в '+s['districts'][did]['name'],did,t,pid);e['salience']=1/(1+fatigue*.25)
        for c in s['cohorts']:
            if c['district']==did:c['familiarity'][pid]=clip(c['familiarity'][pid]+2/(1+fatigue))
    elif action=='mobilize':
        e=emit(s,'mobilization',p['name']+' организует участие своих сторонников в '+s['districts'][did]['name'],did,t,pid)
        for c in s['cohorts']:
            if c['district']==did and (c['identity']==pid or c['trust'][pid]>60):c['turnout_bias']=clip(c['turnout_bias']+1,-10,10)
    elif action=='organize':
        p['organization']=clip(p['organization']+2+a['competence']/100)
        e=emit(s,'organization',p['name']+' развивает местное отделение в '+s['districts'][did]['name'],did,t,pid)
    elif action=='promise':
        field='infra' if t=='services' else 'jobs';baseline=s['districts'][did][field]
        promise={'id':'p'+str(len(s['promises']))+'_'+str(s['week']),'party':pid,'district':did,'topic':t,'field':field,'baseline':baseline,'goal':8.0,'deadline':s['week']+8,'status':'open','made':s['week']}
        s['promises'].append(promise)
        e=emit(s,'promise',p['name']+' обещает улучшить '+data['topics'][t]['name'].lower()+' в '+s['districts'][did]['name']+' за 8 недель',did,t,pid)
    elif action=='listen':
        p['intel']=survey(s,data,pid,rng)
        e=emit(s,'listening',p['name']+' выслушивает жителей и обновляет неполную картину их нужд',did,t,pid)
    elif action=='fundraise':
        p['funds']=clip(p['funds']+7+a['influence']/15,0,200)
        e=emit(s,'fundraising',p['name']+' собирает пожертвования на политическую работу',did,'rights',pid)
        if a['honesty']<45 and rng.random()<(45-a['honesty'])/100:
            p['funds']=clip(p['funds']+10,0,200)
            e=emit(s,'scandal',p['name']+': выявлено скрытое финансирование при сборе средств',did,'rights',pid,[e['id']])
    if e:
        a['memory'].append(e['id']);del a['memory'][:-40]
    p['strategy']=NAMES[action];p['intent']={'action':action,'until':s['week']+3}
    return e

def politics(s,data,rng,emit):
    from .world import forecast,create_party
    initialize(s)
    active=[pid for pid,p in s['parties'].items() if p['active']]
    for pid in active:
        p=s['parties'][pid];a=s['actors'][p['leader']]
        p['funds']=clip(p['funds']+1,0,200)
        p['factions']['purists']=clip(p['factions']['purists']+(.2 if pid in s['governing'] else -.1))
        # No passive omniscient weekly re-reading of all cohorts.
        if not p['intel']['districts']:p['intel']=survey(s,data,pid,rng)
        if s['week']%3==0:
            chosen,options=choose(s,data,pid);e=perform(s,data,pid,chosen,rng,emit)
            a['decision']={'week':s['week'],'action':chosen['action'],'target':chosen['target'],'topic':chosen['topic'],'reason':chosen['reason'],'options':options,'event':e['id'] if e else 0}
        if s['week']%13==0 and p['intel']['share']<18 and p['intel']['public_axes']:
            axis=max(data['axes'],key=lambda x:abs(p['intel']['public_axes'][x]-p['ideology'][x]))
            shift=clip((p['intel']['public_axes'][axis]-p['ideology'][axis])*.12,-8,8)
            p['ideology'][axis]=clip(p['ideology'][axis]+shift,-100,100);p['factions']['purists']=clip(p['factions']['purists']+abs(shift))
            emit(s,'platform',p['name']+' меняет программу по последним доступным оценкам, а не по точным предпочтениям всех жителей',party=pid)
        if p['factions']['purists']>80 and sum(x['active'] for x in s['parties'].values())<6 and rng.random()<.06:
            child=create_party(s,data,p['name']+' — группа '+str(s['next_party']),p['actual_ideology'])
            s['parties'][child]['organization']=p['organization']*.3;p['organization']*=.7;p['factions']['purists']=50
            emit(s,'split','Из '+p['name']+' выделилось новое движение',party=child)
    if s['week']%4==0:
        est=forecast(s)['shares'];s['polls'].append({'week':s['week'],'shares':{p:clip(v+rng.gauss(0,3)) for p,v in est.items()},'error':3.0});del s['polls'][:-24]

def validate(s,data,numeric):
    for a in s['actors'].values():
        d=a['decision']
        if not isinstance(d,dict) or set(d)!={'week','action','target','topic','reason','options','event'} or d['action'] not in NAMES or type(d['week']) is not int or d['week']<0 or type(d['event']) is not int or d['event']<0 or not isinstance(d['reason'],str):raise DataError('god save: actor decision')
        if len(d['options'])>7:raise DataError('god save: decision alternatives')
        for row in d['options']:
            if set(row)!={'action','target','topic','score','reason'} or row['action'] not in NAMES or row['target'] not in s['districts'] or row['topic'] not in data['topics'] or not isinstance(row['reason'],str):raise DataError('god save: decision option')
            numeric(row['score'],-1e6,1e6,'decision score')
    for p in s['parties'].values():
        i=p['intel']
        if set(i)!={'week','sample','districts','share','public_axes'} or type(i['week']) is not int or i['week']<0 or type(i['sample']) is not int or not 0<=i['sample']<=24:raise DataError('god save: intelligence')
        numeric(i['share'],0,100,'observed share')
        if i['public_axes'] and set(i['public_axes'])!=set(data['axes']):raise DataError('god save: observed axes')
        for v in i['public_axes'].values():numeric(v,-100,100,'observed axis')
        for did,r in i['districts'].items():
            if did not in s['districts'] or set(r)!={'support','hardship','jobs','infra','attention'} or set(r['attention'])!=set(data['topics']):raise DataError('god save: observed district')
            for k in ('support','hardship','jobs','infra'):numeric(r[k],0,100,'observed condition')
            for v in r['attention'].values():numeric(v,0,100,'observed issue')
        if set(p['intent'])!={'action','until'} or p['intent']['action'] not in NAMES or type(p['intent']['until']) is not int or p['intent']['until']<0:raise DataError('god save: party intent')
