"""Autonomous cohort simulation, not a candidate campaign. Pure stdlib.
All interventions/effects are explicit data; no Python execution from user text.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import random
from pathlib import Path
from ..engine import DataError, RuleError, DATA_DIR, load_json

SCHEMA = 3
RULES_081 = '843560ea77b761791b698f64ce713e02bf8ed31067b40e1f32fcadb9e83c48cd'
LEGACY_RULES = 'b87796db80f1ae89dd7a1d26350e685327932aa2b43a4c169a06587b0a07c00b'
from . import living, agents, civic


def clamp(x, low=0.0, high=100.0):
    return max(low, min(high, x))


def fingerprint(data):
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def load_data():
    data=load_json(DATA_DIR/'god_world.json')
    try:
        if type(data['schema']) is not int or data['schema']!=SCHEMA:raise ValueError('схема')
        if set(data['axes'])!={'economy','freedom','tradition','ecology'}:raise ValueError('идеологические оси')
        if set(data['topics'])!={'jobs','services','ecology','rights','tradition'}:raise ValueError('политические темы')
        if not 2<=len(data['parties'])<=8 or len(data['districts'])!=4:raise ValueError('состав города')
        for party in data['parties'].values():
            if set(party['ideology'])!=set(data['axes']) or any(type(v) not in (int,float) or not math.isfinite(v) or not -100<=v<=100 for v in party['ideology'].values()):raise ValueError('идеология')
            if not isinstance(party['name'],str) or not party['name'] or not party['aliases']:raise ValueError('название партии')
        for d in data['districts'].values():
            if type(d['population']) is not int or not 100<=d['population']<=1_000_000:raise ValueError('население')
            for key in ('income','infra','jobs','pollution','access'):
                if type(d[key]) not in (int,float) or not math.isfinite(d[key]) or not 0<=d[key]<=100:raise ValueError('район '+key)
        for topic in data['topics'].values():
            if topic['axis'] not in data['axes'] or not topic['aliases']:raise ValueError('тема')
        if set(data['powers'])!={'attention','information','reveal','economy','solidarity','meeting','weather','access','dream','luck','health','infrastructure','encounter','discovery','free_time','coordination'}:raise ValueError('поддерживаемые механизмы')
        for power in data['powers'].values():
            if type(power['cost']) is not int or not 1<=power['cost']<=100 or not power['aliases']:raise ValueError('сила')
        cfg=data['living']
        if set(cfg)!={'base_income','income_factor','family_earners','family_cost','pension_factor','food','housing','housing_income','transport','health','dependents','study_fee','side_income','interest','credit_weeks'}:raise ValueError('бюджеты домохозяйств')
        if any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in cfg.values()) or cfg['interest']>0.1 or cfg['credit_weeks']>52:raise ValueError('финансовые параметры')
        cc=data['civic']
        if set(cc)!={'demand','project_cost','upkeep'} or set(cc['demand'])!=set(civic.KINDS) or any(type(v) not in (int,float) or not 0<v<=1 for v in cc['demand'].values()) or not 1<=cc['project_cost']<=100 or not 0<cc['upkeep']<=10:raise ValueError('параметры учреждений')
        rules=data['rules']
        if type(rules['election_period']) is not int or not 4<=rules['election_period']<=104 or type(rules['first_election']) is not int or rules['first_election']<1:raise ValueError('календарь')
        if type(rules['seats']) is not int or rules['seats']<4 or not 0<=rules['threshold']<=25 or rules['election_system'] not in ('proportional','majoritarian','mixed'):raise ValueError('выборы')
        if rules['energy_max']!=100 or not 0<=rules['energy_regen']<=100 or rules['cohort_limit']<144:raise ValueError('лимиты')
    except (KeyError,TypeError,ValueError) as exc:raise DataError('god_world: '+str(exc)) from exc
    return data


def previous_data(data,schema):
    old=copy.deepcopy(data);old.pop('civic')
    for key in civic.NEW_POWERS:old['powers'].pop(key)
    old['schema']=schema
    if schema==1:old.pop('living')
    return old


def base_attraction(ideology,party,weights):
    total=sum(weights.values())
    if total<=0: raise RuleError('Веса идеологии должны быть положительными')
    return clamp(100*(1-sum(weights[k]*abs(ideology[k]-party[k]) for k in weights)/(200*total)))


def event(s,kind,text,district='all',topic='',party='',causes=None,truth=True):
    e={'id':s['event_id'],'week':s['week'],'kind':kind,'text':text,'district':district,'topic':topic,'party':party,
       'causes':list(causes or []),'truth':bool(truth),'reach':{},'salience':1.0}
    s['event_id']+=1;s['events'].append(e)
    del s['events'][:-600]
    civic.archive(s,e)
    return e


def new_state(data,seed):
    rng=random.Random(seed)
    s={'schema':SCHEMA,'seed':seed,'week_seed':rng.getrandbits(64),'week':1,'revision':0,'energy':100.0,'event_id':1,
       'districts':copy.deepcopy(data['districts']),'parties':copy.deepcopy(data['parties']),'cohorts':[],
       'actors':{},'firms':{},'links':{},'events':[],'powers':[],'promises':[],'projects':[],'movements':[],
       'elections':[],'governing':['labor'],'budget':120.0,'rules':copy.deepcopy(data['rules']),
       'effects':[],'direct_log':[],'editor_used':False,'next_party':1,'polls':[], 'media_trust':{'paper':65.0,'rumor':35.0}}
    names=['Виктор Серов','Анна Белова','Борис Ложкин','Марина Орлова','Павел Зотов','Ирина Климова','Олег Титов','Нина Егорова']
    roles=['leader','leader','leader','journalist','employer','activist','official','organizer']
    for i,(name,role) in enumerate(zip(names,roles)):
        s['actors']['a'+str(i)]={'name':name,'role':role,'age':rng.randint(30,65),'alive':True,'influence':rng.randint(35,80),
           'honesty':rng.randint(35,90),'competence':rng.randint(30,85),'risk':rng.randint(15,80),'health':85.0,
           'goal':{'leader':'получить власть','journalist':'проверить сведения','employer':'сохранить предприятие','activist':'добиться изменений','official':'исполнить решение','organizer':'помочь соседям'}[role],
           'district':list(s['districts'])[i%4],'relations':{},'memory':[]}
    for aid,a in s['actors'].items():a['relations']={b:rng.randint(-30,70) for b in s['actors'] if b!=aid}
    for pid,p in s['parties'].items():
        p.update({'active':True,'trust':55.0,'organization':35.0,'funds':75.0,'competence':s['actors'][p['leader']]['competence'],
                  'factions':{'pragmatists':50.0,'purists':50.0},'actual_ideology':dict(p['ideology']), 'fatigue':{},'strategy':'убеждение','coalition_history':[]})
    for did,d in s['districts'].items():
        s['firms'][did]={'name':('Комбинат' if did=='factory' else 'Предприятия')+' / '+d['name'],'district':did,'capital':55.0,'demand':d['income'],'wage':50.0,'workers':1000,'status':'работает'}
        d.update({'solidarity':35.0,'health':75.0,'housing':50.0,'luck':0.0,'weather':0.0,'maintenance':0.0,'last_crisis':0})
        combinations=[(age,income,religious,parent) for age in ('young','adult','elder') for income in ('lower','middle','upper') for religious in (False,True) for parent in (False,True)]
        count,rest=divmod(d['population'],len(combinations))
        for n,(age,income,religious,parent) in enumerate(combinations):
            cid='c'+str(len(s['cohorts']))
            tags=[income,'religious' if religious else 'secular','parent' if parent else 'single']
            tags.append('student' if age=='young' else 'elder' if age=='elder' else 'business' if income=='upper' else 'worker')
            ideology={'economy':clamp({'lower':-65,'middle':-5,'upper':55}[income]+rng.gauss(0,18),-100,100),
                      'freedom':clamp({'young':50,'adult':10,'elder':-25}[age]+rng.gauss(0,20),-100,100),
                      'tradition':clamp((60 if religious else -40)+rng.gauss(0,15),-100,100),'ecology':clamp((45 if age=='young' else 10)+rng.gauss(0,18),-100,100)}
            c={'id':cid,'district':did,'population':count+(n<rest),'age':{'young':23,'adult':43,'elder':70}[age]+rng.randint(-3,3),
               'tags':tags,'ideology':ideology,'weights':{'economy':2.0 if income=='lower' else 1.0,'freedom':1.2 if age=='young' else .8,'tradition':1.5 if religious else .7,'ecology':1.0},
               'spread':12.0,'income':clamp(d['income']+{'lower':-20,'middle':0,'upper':25}[income]),'stress':25.0,'faith':55.0 if religious else 10.0,
               'engagement':rng.randint(25,70),'identity':'','loyalty':0.0,'goal':'защитить семью' if parent else 'найти возможности',
               'attention':{t:20.0 for t in data['topics']},'trust':{p:55.0 for p in s['parties']},'memory':{p:0.0 for p in s['parties']},
               'familiarity':{p:60.0 for p in s['parties']},'known':[],'perceived':{p:dict(x['ideology']) for p,x in s['parties'].items()},
               'norm':35.0,'turnout_bias':0.0}
            if parent:c['attention']['services']=40
            if income=='lower':c['attention']['jobs']=50
            if religious:c['attention']['tradition']=45
            s['cohorts'].append(c)
    ids=list(s['districts'])
    s['links']={a:{b:(1.0 if a==b else .35 if abs(ids.index(a)-ids.index(b))==1 else .15) for b in ids} for a in ids}
    for c in s['cohorts']:living.initialize(c)
    agents.initialize(s)
    civic.initialize(s,data);civic.evaluate_institutions(s,data,event,False)
    event(s,'origin','Город живёт самостоятельно. Первые выборы — на неделе '+str(data['rules']['first_election'])+'.')
    return s


def attraction(s,c,pid):
    p=s['parties'][pid]
    base=base_attraction(c['ideology'],c['perceived'].get(pid,p['ideology']),c['weights'])
    actor=s['actors'].get(p['leader'],{})
    components={'ideology':base,'trust':(c['trust'].get(pid,50)-50)*.28,'memory':c['memory'].get(pid,0),
                'leader':(actor.get('influence',50)-50)*.06,'familiarity':(c['familiarity'].get(pid,50)-50)*.05,
                'civic':civic.member_attraction(s,c,pid),
                'identity':c['loyalty']*.10*(.5+c['norm']/100) if c['identity']==pid else 0.0,'editor':c.get('editor_bonus',{}).get(pid,0)}
    return clamp(sum(components.values())),components


def choice(s,c,strategic=True):
    active=[pid for pid,p in s['parties'].items() if p['active']]
    if not active:return {},0.0
    values={pid:attraction(s,c,pid)[0] for pid in active}
    top=max(values.values());temp=12+c['spread']*.3
    exp={p:math.exp((v-top)/temp) for p,v in values.items()}
    if strategic and s['polls']:
        poll=s['polls'][-1]['shares'];best=max(active,key=lambda p:poll.get(p,0))
        for p in active:
            if poll.get(p,0)<s['rules']['threshold'] and p!=best:
                transfer=exp[p]*.20;exp[p]-=transfer;exp[best]+=transfer
    total=sum(exp.values());probs={p:v/total for p,v in exp.items()}
    d=s['districts'][c['district']]
    turnout=clamp(.35+c['engagement']/200+(top-60)/250+(d['access']-70)/250-c['stress']/500+c['turnout_bias']/100,.05,.95)
    return probs,turnout


def forecast(s):
    votes={p:0.0 for p,x in s['parties'].items() if x['active']};voters=0
    for c in s['cohorts']:
        probs,t=choice(s,c);n=c['population']*t;voters+=n
        for p,pr in probs.items():votes[p]+=n*pr
    total=sum(votes.values());return {'votes':votes,'shares':{p:100*v/total if total else 0 for p,v in votes.items()},'turnout':100*voters/max(1,sum(c['population'] for c in s['cohorts']))}


def allocate(votes,seats,threshold):
    total=sum(votes.values());eligible={p:v for p,v in votes.items() if total and 100*v/total>=threshold}
    result={p:0 for p in votes}
    if not eligible:return result
    for _ in range(seats):
        p=max(eligible,key=lambda k:(eligible[k]/(result[k]+1),k));result[p]+=1
    return result


def election(s,data,rng):
    active=[p for p,x in s['parties'].items() if x['active']]
    votes={p:0 for p in active};regional={d:{p:0 for p in active} for d in s['districts']}
    population=sum(c['population'] for c in s['cohorts']);voters=0
    for c in s['cohorts']:
        probs,t=choice(s,c);n=int(clamp(round(c['population']*t+rng.gauss(0,math.sqrt(c['population']*t*(1-t)))),0,c['population']))
        voters+=n
        # Exact conservation, no individual-per-frame loop.
        raw={p:n*probs[p] for p in active};counts={p:int(v) for p,v in raw.items()}
        for p in sorted(active,key=lambda p:(-(raw[p]-counts[p]),p))[:n-sum(counts.values())]:counts[p]+=1
        for p,v in counts.items():votes[p]+=v;regional[c['district']][p]+=v
    seats=allocate(votes,s['rules']['seats'],s['rules']['threshold'])
    if s['rules']['election_system'] in ('majoritarian','mixed') and active:
        district_seats={p:0 for p in active}
        for row in regional.values():district_seats[max(row,key=lambda p:(row[p],p))]+=1
        if s['rules']['election_system']=='majoritarian':seats=district_seats
        else:
            proportional=allocate(votes,s['rules']['seats']-len(regional),s['rules']['threshold'])
            seats={p:proportional[p]+district_seats[p] for p in active}
    ranked=sorted(active,key=lambda p:(-seats.get(p,0),-votes[p],p));coalition=[];held=0;majority=sum(seats.values())/2
    if ranked and sum(seats.values())>0:
        first=ranked[0];coalition=[first];held=seats[first]
        others=sorted(ranked[1:],key=lambda p:sum(abs(s['parties'][p]['ideology'][a]-s['parties'][first]['ideology'][a]) for a in data['axes']))
        for p in others:
            if held>majority:break
            coalition.append(p);held+=seats[p]
    s['governing']=coalition
    result={'week':s['week'],'votes':votes,'shares':{p:100*v/voters if voters else 0 for p,v in votes.items()},'seats':seats,'regional':regional,'voters':voters,'population':population,'turnout':100*voters/max(1,population),'government':coalition,'system':s['rules']['election_system']}
    s['elections'].append(result);del s['elections'][:-24]
    names=', '.join(s['parties'][p]['name'] for p in coalition) or 'нет действующих партий'
    event(s,'election','Выборы: явка '+str(round(result['turnout'],1))+'%; правящая коалиция — '+names)
    s['rules']['next_election']=s['week']+s['rules']['election_period']
    for p in active:
        s['parties'][p]['coalition_history'].append({'week':s['week'],'government':p in coalition})
        del s['parties'][p]['coalition_history'][:-24]
        s['parties'][p]['organization']=clamp(s['parties'][p]['organization']+(3 if p in coalition else 1))
    return result


def affected(s,target='all'):
    if not isinstance(target,str):return []
    groups=target.split('|')
    def matches(c,part):
        return all(x=='all' or c['district']==x or c['id']==x or x in c['tags'] for x in part.split('&'))
    return [c for c in s['cohorts'] if any(matches(c,g) for g in groups)]


def apply_power(s,data,command):
    key=command['power'];target=command.get('target','all');topic=command.get('topic','');strength=command.get('strength',15);duration=command.get('duration',4)
    if key not in data['powers']:raise RuleError('Неизвестная сила')
    if type(strength) not in (int,float) or not math.isfinite(strength) or not -30<=strength<=30 or strength==0:raise RuleError('Сила: от −30 до 30, кроме нуля')
    if type(duration) is not int or not 1<=duration<=12:raise RuleError('Срок: 1–12 недель')
    cohorts=affected(s,target)
    if not cohorts:raise RuleError('Нет такой аудитории')
    if key in ('attention','information') and topic not in data['topics']:raise RuleError('Уточните политическую тему')
    if topic and topic not in data['topics']:raise RuleError('Неизвестная тема')
    cost=math.ceil(data['powers'][key]['cost']*(abs(strength)/15)*(1+.08*(duration-1)))
    if s['energy']<cost:raise RuleError('Не хватает божественного влияния: нужно '+str(cost))
    if key=='reveal':
        source=next((e for e in s['events'] if e['id']==command.get('event_id')),None)
        if not source or not source['truth']:raise RuleError('Можно раскрыть только существующий проверяемый факт; выберите событие')
    if key in ('encounter','discovery','coordination') and strength<0:raise RuleError('Этот механизм создаёт возможность; нужна положительная сила')
    s['energy']-=cost
    cause=event(s,'miracle',data['powers'][key]['name']+': '+target+'; сила '+str(strength)+', срок '+str(duration)+' нед.',target,topic)
    eff={'power':key,'target':target,'topic':topic,'strength':strength,'until':s['week']+duration-1,'cause':cause['id']}
    eff.update({k:command[k] for k in ('document_id','actor_a','actor_b','association_id') if k in command})
    s['effects'].append(eff)
    if key in civic.NEW_POWERS:civic.power(s,data,{**command,'strength':strength,'duration':duration,'target':target},cause)
    if key=='reveal':
        source['salience']+=abs(strength)/10
        source['revealed']=True
        cause['causes'].append(source['id'])
    if key=='meeting':
        districts={c['district'] for c in cohorts}
        for a in districts:
            for b in s['links'][a]:s['links'][a][b]=clamp(s['links'][a][b]+abs(strength)/150,0,1)
    if key=='dream':
        for c in cohorts:
            c['faith']=clamp(c['faith']+strength*(1 if 'religious' in c['tags'] else .35))
        event(s,'interpretation','Знамение толкуют по-разному: община видит покровительство; скептики — совпадение.',target,'tradition',causes=[cause['id']])
    return cause,cost


def power_effects(s,data):
    for d in s['districts'].values():d['weather']=0;d['luck']=0;d['maintenance']=0
    for e in s['effects']:
        if e['until']<s['week']:continue
        cohorts=affected(s,e['target']);districts={c['district'] for c in cohorts};v=e['strength'];key=e['power']
        if key in ('attention','information'):
            for c in cohorts:
                c['attention'][e['topic']]=clamp(c['attention'][e['topic']]+v*.35)
                if key=='information':c['engagement']=clamp(c['engagement']+v*.05)
        if key in ('economy','health','solidarity','infrastructure','access'):
            field=data['powers'][key]['field']
            # A cohort-targeted blessing affects only its population, not the whole district.
            for c in cohorts:
                if field=='income':c['income']=clamp(c['income']+v*.12)
                elif field=='health':c['stress']=clamp(c['stress']-v*.1)
                elif field=='solidarity':c['engagement']=clamp(c['engagement']+v*.08)
            for did in districts:
                total=sum(c['population'] for c in s['cohorts'] if c['district']==did)
                proportion=sum(c['population'] for c in cohorts if c['district']==did)/max(1,total)
                s['districts'][did][field]=clamp(s['districts'][did][field]+v*.15*proportion)
        if key in ('weather','luck'):
            for did in districts:s['districts'][did][key]+=v


def notify(s,data,e,magnitude):
    pid=e['party']
    if not pid:return
    for c in s['cohorts']:
        if e['district'] not in ('all',c['district']) and c['id'] not in e['reach']:continue
        reach=e['reach'].get(c['id'],0)
        if reach<=0:continue
        importance=.5+c['attention'].get(e['topic'],20)/50
        c['memory'][pid]=clamp(c['memory'].get(pid,0)+magnitude*importance*reach,-30,30)
        c['trust'][pid]=clamp(c['trust'].get(pid,50)+magnitude*.8*reach)


def information(s,data,rng):
    effects=[(x,{c['id'] for c in affected(s,x['target'])}) for x in s['effects'] if x['power']=='information' and x['until']>=s['week']]
    for e in s['events'][-100:]:
        age=s['week']-e['week']
        if age<0 or age>16:continue
        for c in s['cohorts']:
            old=e['reach'].get(c['id'],0)
            local=e['district'] in ('all',c['district'],c['id']) or e['district'] in c['tags']
            connection=1.0 if local else s['links'][c['district']].get(e['district'],.2)
            source_trust=s['media_trust']['paper'] if e['truth'] else s['media_trust']['rumor']
            topical=1+c['attention'].get(e['topic'],0)/80
            spread=.055*connection*topical*e['salience']*(source_trust/65)*(1-old)
            spread+=sum(x['strength']/500 for x,ids in effects if x['topic']==e['topic'] and c['id'] in ids)
            now=clamp(old+spread,0,1);e['reach'][c['id']]=now
            if now>.10 and e['id'] not in c['known']:
                c['known'].append(e['id']);del c['known'][:-80]
                if e['party']:
                    magnitude={'promise_kept':5,'promise_partial':1,'promise_broken':-6,'policy':2,'campaign':1,'opening_claim':2,'scandal':-5,'investigation':-5,'aid':2}.get(e['kind'],0)
                    if not e['truth']:magnitude*=.4
                    importance=.5+c['attention'].get(e['topic'],20)/50
                    if e['kind']=='policy' and e.get('position') is not None:
                        axis=data['topics'][e['topic']]['axis'];magnitude*=1-abs(c['ideology'][axis]-e['position'])/100
                    pid=e['party'];c['memory'][pid]=clamp(c['memory'].get(pid,0)+magnitude*importance,-30,30)
                    c['trust'][pid]=clamp(c['trust'].get(pid,50)+magnitude*.7)
                    c['perceived'][pid]=dict(s['parties'][pid]['ideology'])


def politics(s,data,rng):
    agents.politics(s,data,rng,event)


def government(s,data,rng):
    civic.project_tick(s,data,rng,event)
    for promise in s['promises']:
        if promise['status']!='open':continue
        if promise.get('institution'):
            gain=promise['baseline']-s['civic']['institutions'][promise['institution']]['delay']
        else:gain=s['districts'][promise['district']][promise['field']]-promise['baseline']
        if gain>=promise['goal']:status='kept'
        elif s['week']>=promise['deadline']:status='partial' if gain>promise['goal']*.4 else 'broken'
        else:continue
        promise['status']=status
        contributors=[p for p in s['projects'] if p['party']==promise['party'] and p['stage']=='operating' and p['completed']>=promise['made'] and p['district']==promise['district'] and (not promise.get('institution') or p['institution']==promise['institution'])]
        credited=bool(contributors);promise['credited']=credited
        kind='promise_'+status if status=='broken' or credited else 'promise_satisfied'
        text=s['parties'][promise['party']]['name']+': '+('условия улучшились, но собственное исполнение не подтверждено' if status!='broken' and not credited else {'kept':'обещание выполнено своим проектом','partial':'обещание выполнено частично','broken':'обещание сорвано'}[status])
        event(s,kind,text,promise['district'],promise['topic'],promise['party'],[p['last_event'] for p in contributors])
        s['parties'][promise['party']]['trust']=clamp(s['parties'][promise['party']]['trust']+({'kept':4,'partial':0,'broken':-5}[status] if status=='broken' or credited else 0))
    del s['promises'][:-200]


def society(s,data,rng):
    for firm in s['firms'].values():
        d=s['districts'][firm['district']]
        local=[c for c in s['cohorts'] if c['district']==firm['district'] and c['population']]
        consumption=sum(c['population']*(c['household']['paid']/max(1,c['household']['needs']) if c['household']['needs'] else 1) for c in local)/max(1,sum(c['population'] for c in local))
        firm['demand']+=.08*(d['income']*consumption-firm['demand'])
        firm['capital']=clamp(firm['capital']+(firm['demand']-firm['wage'])*.06-max(0,d['weather'])*.02)
        if s['week']%8==0:
            if firm['capital']>62:
                firm['capital']-=10;firm['workers']+=25;d['jobs']=clamp(d['jobs']+1.5)
                event(s,'employer',firm['name']+' расширяет набор работников',firm['district'],'jobs')
            elif firm['capital']<30 and firm['workers']>200:
                firm['workers']-=25;firm['capital']+=3;d['jobs']=clamp(d['jobs']-2)
                event(s,'employer',firm['name']+' сокращает штат из-за недостатка средств',firm['district'],'jobs')
    for did,d in s['districts'].items():
        d['infra']=clamp(d['infra']-.32-max(0,d['weather'])*.012)
        d['jobs']=clamp(d['jobs']+rng.gauss(0,.5)+(d['income']-50)*.005)
        d['income']=clamp(d['income']+(d['jobs']-60)*.006)
        d['housing']=clamp(d['housing']+(d['income']-50)*.006)
        vulnerability=clamp((100-d['infra'])/100-d['luck']/100,0,2)
        if d['weather']>10:vulnerability+=d['weather']/70
        if rng.random()<.018*vulnerability:
            damage=3+abs(d['weather'])*.15;d['infra']=clamp(d['infra']-damage);d['last_crisis']=s['week']
            causes=[e['cause'] for e in s['effects'] if e['power']=='weather' and e['until']>=s['week'] and any(c['district']==did for c in affected(s,e['target']))]
            event(s,'crisis','Сбой инфраструктуры в '+d['name']+'; износ '+str(round(100-d['infra']))+'%',did,'services',s['governing'][0] if s['governing'] else '',causes)
            d['solidarity']=clamp(d['solidarity']+4)
    for c in s['cohorts']:
        d=s['districts'][c['district']]
        target_income=clamp(d['income']+(-20 if 'lower' in c['tags'] else 25 if 'upper' in c['tags'] else 0))
        c['income']+=.06*(target_income-c['income'])
        c['stress']=clamp(c['stress']+.08*((100-d['jobs']+100-d['infra'])/2-c['stress']))
        for t in c['attention']:c['attention'][t]=clamp(c['attention'][t]*.97+0.6)
        c['attention']['jobs']=clamp(c['attention']['jobs']+(100-d['jobs'])*.012)
        c['attention']['services']=clamp(c['attention']['services']+(100-d['infra'])*.015)
        c['attention']['ecology']=clamp(c['attention']['ecology']+d['pollution']*.009)
        for p in c['memory']:c['memory'][p]*=.97
        probs,t=choice(s,c)
        if probs:
            best=max(probs,key=probs.get)
            if probs[best]>.50:
                if c['identity']==best:c['loyalty']=clamp(c['loyalty']+.4)
                elif c['loyalty']<10:c['identity']=best;c['loyalty']=12
                else:c['loyalty']-=.5
        c['norm']+=.03*(d['solidarity']-c['norm'])
        c['weights']['tradition']=.7+c['faith']/100*1.2
        c['ideology']['tradition']=clamp(c['ideology']['tradition']+(c['faith']-40)*.005,-100,100)
        # Ideology evolves slowly from experienced material conditions.
        c['ideology']['economy']=clamp(c['ideology']['economy']+(c['income']-50)*.003,-100,100)
        if s['week']%52==0:
            c['age']+=1
            if c['age']>=65 and 'elder' not in c['tags']:
                c['tags']=[x for x in c['tags'] if x not in ('worker','business','student')]+['elder']
            if c['age']>=30 and 'student' in c['tags']:c['tags']=[x for x in c['tags'] if x!='student']+['worker']
            # Population turnover is aggregate, not named households.
            loss=round(c['population']*(.018 if 'elder' in c['tags'] else .004)*(1+(100-d['health'])/150))
            c['population']=max(0,c['population']-loss)
    if s['week']%52==0:
        for did,d in s['districts'].items():
            young=[c for c in s['cohorts'] if c['district']==did and 'student' in c['tags']]
            entrants=round(d['population']*.009)
            if young:
                each,remainder=divmod(entrants,len(young))
                for i,c in enumerate(young):c['population']+=each+(i<remainder)
            event(s,'generation',str(entrants)+' молодых жителей получили право участия; смена поколения.',did)
    if s['week']%13==0:
        for did,d in s['districts'].items():
            local=[c for c in s['cohorts'] if c['district']==did and c['population']]
            pressure=max(c['attention']['services']+c['attention']['jobs'] for c in local) if local else 0
            exists=next((m for m in s['movements'] if m['district']==did and m['active']),None)
            if pressure>70 and d['solidarity']>25 and not exists:
                m={'id':'m'+str(len(s['movements'])),'district':did,'topic':'services' if d['infra']<d['jobs'] else 'jobs','active':True,'strength':pressure*.4,'born':s['week']}
                s['movements'].append(m);event(s,'movement','Жители '+d['name']+' создали инициативную группу',did,m['topic'])
            elif exists:
                exists['strength']=clamp(exists['strength']+(pressure-60)*.05)
                if pressure<40:exists['active']=False;event(s,'compromise','Инициативная группа снизила активность после улучшения условий',did,exists['topic'])
        # Migration changes geography, preserves unique people and total count.
        poorest=min(s['districts'],key=lambda d:s['districts'][d]['income']);richest=max(s['districts'],key=lambda d:s['districts'][d]['income'])
        if poorest!=richest:
            candidates=[c for c in s['cohorts'] if c['district']==poorest and 'elder' not in c['tags'] and c['population']>10]
            if candidates:
                origin=rng.choice(candidates);dest=next((c for c in s['cohorts'] if c['district']==richest and set(c['tags'])==set(origin['tags'])),None)
                if dest:
                    movers=max(1,int(origin['population']*.02));living.transfer_mean(origin,dest,movers);origin['population']-=movers;dest['population']+=movers
                    event(s,'migration',str(movers)+' жителей переехали из '+s['districts'][poorest]['name']+' в '+s['districts'][richest]['name'],richest,'jobs')
    for did,d in s['districts'].items():d['population']=sum(c['population'] for c in s['cohorts'] if c['district']==did)
    for aid,a in list(s['actors'].items()):
        if not a['alive']:continue
        if s['week']%52==0:a['age']+=1
        if a['age']>75 and rng.random()<.01:
            retire_actor(s,data,aid,'возраст и здоровье')
        elif a['role']=='activist' and s['week']%7==0:
            d=s['districts'][a['district']];d['solidarity']=clamp(d['solidarity']+a['influence']/60)
            event(s,'aid',a['name']+' организует соседскую взаимопомощь',a['district'],'tradition')
    s['effects']=[e for e in s['effects'] if e['until']>=s['week']]


def create_party(s,data,name,ideology):
    if not isinstance(name,str) or not 1<=len(name.strip())<=50:raise RuleError('Название партии: 1–50 символов')
    if len([p for p in s['parties'].values() if p['active']])>=8:raise RuleError('Не более восьми действующих партий')
    if len(s['parties'])>=24:raise RuleError('Архив ограничен 24 партиями; начните новый мир')
    if any(p['name'].casefold()==name.strip().casefold() for p in s['parties'].values()):raise RuleError('Название уже занято')
    if not isinstance(ideology,dict) or set(ideology)!=set(data['axes']) or any(type(v) not in (int,float) or not math.isfinite(v) or not -100<=v<=100 for v in ideology.values()):raise RuleError('Идеология: четыре оси от −100 до 100')
    pid='new'+str(s['next_party']);s['next_party']+=1
    aid='a'+str(len(s['actors']))
    s['actors'][aid]={'name':'Лидер '+name.strip(),'role':'leader','age':35,'alive':True,'influence':40,'honesty':55,'competence':50,'risk':50,'health':80.0,'goal':'создать представительство','district':next(iter(s['districts'])),'relations':{},'memory':[]}
    s['parties'][pid]={'name':name.strip(),'aliases':[name.strip().lower()],'ideology':dict(ideology),'actual_ideology':dict(ideology),'leader':aid,'color':'#718B69','active':True,'trust':50.0,'organization':10.0,'funds':35.0,'competence':50.0,'factions':{'pragmatists':50.0,'purists':50.0},'fatigue':{},'strategy':'убеждение','coalition_history':[]}
    for c in s['cohorts']:
        c['trust'][pid]=50;c['memory'][pid]=0;c['familiarity'][pid]=10;c['perceived'][pid]=dict(ideology)
    agents.initialize(s)
    return pid


def retire_actor(s,data,aid,reason):
    if aid not in s['actors'] or not s['actors'][aid]['alive']:raise RuleError('Персонаж уже выбыл или отсутствует')
    a=s['actors'][aid];a['alive']=False
    e=event(s,'succession',a['name']+' выбыл: '+reason,a['district'])
    for p in s['parties'].values():
        if p['active'] and p['leader']==aid:
            successor='a'+str(len(s['actors']))
            replacement=copy.deepcopy(a);replacement.update({'name':'Преемник '+a['name'],'age':34,'alive':True,'influence':max(20,a['influence']-12),'memory':[e['id']]})
            replacement['decision']={'week':0,'action':'rest','target':'','topic':'','reason':'Новый лидер ещё не принял решение','options':[],'event':0}
            s['actors'][successor]=replacement;p['leader']=successor;p['organization']=clamp(p['organization']-6)
    return e


def direct(s,data,command):
    op=command.get('op');pid=command.get('party');target=command.get('target','all');value=command.get('value',20)
    if op in ('popularity','dissolve','ideology') and (pid not in s['parties'] or not s['parties'][pid]['active']):raise RuleError('Выберите действующую партию')
    if op=='popularity':
        if type(value) not in (int,float) or not math.isfinite(value) or not -100<=value<=100:raise RuleError('Изменение: −100..100 пунктов')
        cs=affected(s,target)
        if not cs:raise RuleError('Нет такой аудитории')
        for c in cs:
            bonus=c.setdefault('editor_bonus',{});bonus[pid]=clamp(bonus.get(pid,0)+value,-100,100)
        text='Прямо изменена привлекательность '+s['parties'][pid]['name']+' на '+str(value)+' пунктов; '+target
    elif op=='dissolve':
        if len([p for p in s['parties'].values() if p['active']])<=1:raise RuleError('Нельзя распустить последнюю партию')
        s['parties'][pid]['active']=False;s['governing']=[p for p in s['governing'] if p!=pid]
        for c in s['cohorts']:
            if c['identity']==pid:c['identity']='';c['loyalty']=0
        for p in s['promises']:
            if p['party']==pid and p['status']=='open':p['status']='cancelled'
        text='Распущена '+s['parties'][pid]['name']+'; избиратели остаются в городе'
    elif op=='create':
        new=create_party(s,data,command.get('name',''),command.get('ideology',{}));text='Создана '+s['parties'][new]['name']
    elif op=='ideology':
        axis=command.get('axis')
        if axis not in data['axes'] or type(value) not in (int,float) or not math.isfinite(value) or not -100<=value<=100:raise RuleError('Ось и значение −100..100')
        s['parties'][pid]['ideology'][axis]=value;text='Напрямую изменена программа '+s['parties'][pid]['name']
        # Perceived positions change after information, not instant omniscience.
        event(s,'platform',text,party=pid)
    elif op=='rules':
        key=command.get('key')
        if key=='election_system' and value in ('proportional','majoritarian','mixed'):s['rules'][key]=value
        elif key=='threshold' and type(value) in (int,float) and math.isfinite(value) and 0<=value<=25:s['rules'][key]=value
        elif key=='election_period' and type(value) is int and 4<=value<=104:s['rules'][key]=value
        else:raise RuleError('Недопустимое правило выборов')
        text='Прямо изменено правило '+key+': '+str(value)
    elif op=='retire':
        e=retire_actor(s,data,command.get('actor'),'прямое вмешательство бога');text=e['text']
    elif op=='resource':
        did=command.get('district');field=command.get('field')
        if did not in s['districts'] or field not in ('income','infra','jobs','pollution','access','health','solidarity','housing') or type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=100:raise RuleError('Район, показатель и значение 0..100')
        s['districts'][did][field]=value;text='Прямо изменён '+field+' в '+s['districts'][did]['name']
    else:raise RuleError('Неизвестная прямая операция')
    s['editor_used']=True
    e=event(s,'direct',text,target,party=pid or '')
    s['direct_log'].append({'week':s['week'],'event':e['id'],'command':copy.deepcopy(command)});del s['direct_log'][:-100]
    return e


def advance(s,data):
    rng=random.Random(s['week_seed']);start=s['event_id']
    before={(c['id'],pid):attraction(s,c,pid) for c in s['cohorts'] for pid,p in s['parties'].items() if p['active']}
    power_effects(s,data)
    society(s,data,rng)
    living.tick(s,data,rng,event)
    civic.evaluate_institutions(s,data,event)
    for e in s['effects']:
        if e['power']=='free_time' and e['until']>=s['week']:
            for c in affected(s,e['target']):
                c['household']['free_time']=clamp(c['household']['free_time']+e['strength']*.5)
                c['engagement']=clamp(c['engagement']+e['strength']*.01)
    civic.associations(s,data,rng,event)
    civic.meetings(s,data,rng,event)
    politics(s,data,rng)
    government(s,data,rng)
    civic.investigations(s,data,rng,event)
    information(s,data,rng)
    civic.record_changes(s,before,attraction,start)
    result=None
    if s['week']>=s['rules'].get('next_election',s['rules']['first_election']):result=election(s,data,rng)
    s['energy']=clamp(s['energy']+s['rules']['energy_regen'],0,s['rules']['energy_max'])
    s['week']+=1;s['revision']+=1;s['week_seed']=rng.getrandbits(64)
    return {'events':[e for e in s['events'] if e['id']>=start],'election':result}


def validate_state(s,data,legacy=False):
    def walk(x):
        if isinstance(x,float) and not math.isfinite(x):raise DataError('god save: NaN/Infinity')
        if isinstance(x,dict):
            for v in x.values():walk(v)
        elif isinstance(x,list):
            if len(x)>10000:raise DataError('god save: слишком длинный список')
            for v in x:walk(v)
        elif not isinstance(x,(str,int,float,bool,type(None))):raise DataError('god save: неизвестный тип')
    walk(s)
    template_keys={'schema','seed','week_seed','week','revision','energy','event_id','districts','parties','cohorts','actors','firms','links','events','powers','promises','projects','movements','elections','governing','budget','rules','effects','direct_log','editor_used','next_party','polls','media_trust'}
    if not legacy:template_keys.add('civic')
    if not isinstance(s,dict) or set(s)!=template_keys or type(s['schema']) is not int or s['schema']!=(int(legacy) if legacy else SCHEMA):raise DataError('god save: схема нового режима, не сохранение кандидата')
    for key in ('seed','week_seed','week','revision','event_id','next_party'):
        if type(s[key]) is not int or s[key]<0:raise DataError('god save: '+key)
    if s['week']<1 or not 0<=s['energy']<=s['rules']['energy_max']:raise DataError('god save: время / влияние')
    if set(s['districts'])!=set(data['districts']) or not 1<=len(s['parties'])<=24 or not 1<=len(s['cohorts'])<=data['rules']['cohort_limit']:raise DataError('god save: состав города')
    ids=set()
    for c in s['cohorts']:
        if c['id'] in ids or c['district'] not in s['districts'] or type(c['population']) is not int or c['population']<0:raise DataError('god save: когорта')
        ids.add(c['id'])
        if set(c['ideology'])!=set(data['axes']) or set(c['weights'])!=set(data['axes']) or any(not -100<=v<=100 for v in c['ideology'].values()) or any(type(v) not in (int,float) or v<=0 for v in c['weights'].values()):raise DataError('god save: идеология')
        if len(c['tags'])!=len(set(c['tags'])) or any(t not in data['tags'] for t in c['tags']):raise DataError('god save: социальные признаки')
        for key in ('trust','memory','familiarity','perceived'):
            if set(c[key])!=set(s['parties']):raise DataError('god save: оценки партий')
    for did,d in s['districts'].items():
        if d['population']!=sum(c['population'] for c in s['cohorts'] if c['district']==did):raise DataError('god save: двойной подсчёт населения')
        for key in ('income','infra','jobs','pollution','access','health','solidarity','housing'):
            if not 0<=d[key]<=100:raise DataError('god save: показатель района')
    for pid,p in s['parties'].items():
        if set(p['ideology'])!=set(data['axes']) or any(not -100<=v<=100 for v in p['ideology'].values()) or p['leader'] not in s['actors'] or type(p['active']) is not bool:raise DataError('god save: партия')
    if not any(p['active'] for p in s['parties'].values()):raise DataError('god save: нет действующих партий')
    if any(p not in s['parties'] or not s['parties'][p]['active'] for p in s['governing']):raise DataError('god save: правительство')
    rules=s['rules']
    if rules['election_system'] not in ('proportional','majoritarian','mixed') or not 0<=rules['threshold']<=25 or type(rules['election_period']) is not int or not 4<=rules['election_period']<=104:raise DataError('god save: правила выборов')
    for eff in s['effects']:
        if eff['power'] not in data['powers'] or not affected(s,eff['target']) or type(eff['until']) is not int:raise DataError('god save: воздействие')
    def numeric(value,low,high,label):
        if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:raise DataError('god save: '+label)
    numeric(s['budget'],0,300,'budget')
    if type(s['editor_used']) is not bool:raise DataError('god save: флаг редактора')
    for c in s['cohorts']:
        for key in ('income','stress','faith','engagement','loyalty','norm','spread'):
            numeric(c[key],0,100,key)
        numeric(c['turnout_bias'],-10,10,'turnout')
        if set(c['attention'])!=set(data['topics']):raise DataError('god save: темы')
        for v in c['attention'].values():numeric(v,0,100,'внимание')
        for p in s['parties']:
            numeric(c['trust'][p],0,100,'доверие');numeric(c['memory'][p],-30,30,'память');numeric(c['familiarity'][p],0,100,'знакомство')
            if set(c['perceived'][p])!=set(data['axes']):raise DataError('god save: воспринимаемая идеология')
            for v in c['perceived'][p].values():numeric(v,-100,100,'идеология')
        for p,v in c.get('editor_bonus',{}).items():
            if p not in s['parties']:raise DataError('god save: бонус неизвестной партии')
            numeric(v,-100,100,'прямой бонус')
    for p in s['parties'].values():
        for key in ('trust','organization','competence'):numeric(p[key],0,100,key)
        numeric(p['funds'],0,200,'funds')
    event_ids=set()
    for e in s['events']:
        if type(e['id']) is not int or e['id'] in event_ids or type(e['week']) is not int or e['week']<1 or not isinstance(e['text'],str) or type(e['truth']) is not bool:raise DataError('god save: хроника')
        event_ids.add(e['id'])
        for cid,v in e['reach'].items():
            if cid not in ids:raise DataError('god save: адресат новости')
            numeric(v,0,1,'охват')
    for e in s['effects']:
        numeric(e['strength'],-30,30,'сила')
        if e['topic'] and e['topic'] not in data['topics']:raise DataError('god save: тема силы')
    if set(s['firms'])!=set(s['districts']):raise DataError('god save: предприятия')
    for firm in s['firms'].values():
        if firm['district'] not in s['districts'] or type(firm['workers']) is not int or firm['workers']<0:raise DataError('god save: предприятие')
        for key in ('capital','demand','wage'):numeric(firm[key],0,100,key)
    for a in s['actors'].values():
        if type(a['alive']) is not bool or a['district'] not in s['districts']:raise DataError('god save: персонаж')
        for key in ('influence','honesty','competence','risk','health'):numeric(a[key],0,100,key)
    for x in s['promises']:
        if x['party'] not in s['parties'] or x['district'] not in s['districts'] or x['topic'] not in data['topics'] or x['status'] not in ('open','kept','partial','broken','cancelled'):raise DataError('god save: обещание')
    for x in s['projects']:
        if x['party'] not in s['parties'] or x['district'] not in s['districts'] or x['field'] not in ('infra','jobs'):raise DataError('god save: проект')
    if not legacy or legacy==2:
        for c in s['cohorts']:living.validate(c,numeric)
        agents.validate(s,data,numeric)
    if not legacy:civic.validate(s,data,numeric)
    return s


class World:
    def __init__(self,seed=None,data=None):
        import secrets
        if seed is None:seed=secrets.randbits(64)
        if type(seed) is not int or not 0<=seed<2**64:raise RuleError('Зерно города: целое 0..2^64−1')
        self.data=data or load_data();self.state=new_state(self.data,seed);validate_state(self.state,self.data);self.undo_buffer=[];self.migration_notice=''

    def step(self,weeks=1,stop_at_election=True):
        if type(weeks) is not int or not 1<=weeks<=104:raise RuleError('1–104 недели за запуск')
        reports=[]
        # Entire requested run is transactional if a rule/data error occurs.
        scratch=copy.deepcopy(self.state)
        for _ in range(weeks):
            report=advance(scratch,self.data);reports.append(report)
            if report['election'] and stop_at_election:break
        validate_state(scratch,self.data);self.state=scratch
        return reports

    def intervene(self,command):
        if not isinstance(command,dict) or set(command)-{'power','target','topic','strength','duration','event_id','document_id','actor_a','actor_b','association_id'}:raise RuleError('Неверная структура вмешательства')
        scratch=copy.deepcopy(self.state);out=apply_power(scratch,self.data,command);scratch['revision']+=1
        validate_state(scratch,self.data);self.state=scratch;return out

    def direct(self,command):
        if not isinstance(command,dict) or set(command)-{'op','party','target','value','name','ideology','axis','key','actor','district','field'}:raise RuleError('Неверная структура прямой операции')
        before=copy.deepcopy(self.state);scratch=copy.deepcopy(self.state);out=direct(scratch,self.data,command);scratch['revision']+=1
        validate_state(scratch,self.data);self.undo_buffer.append(before);del self.undo_buffer[:-3];self.state=scratch;return out

    def undo(self):
        if not self.undo_buffer:raise RuleError('Нет снимка прямого вмешательства в этой сессии')
        self.state=self.undo_buffer.pop();return self.state

    def save(self,path):
        path=Path(path)
        payload={'format':'god-world','schema':SCHEMA,'rules':fingerprint(self.data),'state':self.state}
        envelope={'payload':payload,'checksum':fingerprint(payload)}
        temp=path.with_name(path.name+'.tmp')
        try:
            path.parent.mkdir(parents=True,exist_ok=True)
            temp.write_text(json.dumps(envelope,ensure_ascii=False,separators=(',',':')),encoding='utf-8');temp.replace(path)
        except OSError as exc:raise DataError('Не удалось сохранить мир: '+str(exc)) from exc

    def load(self,path):
        try:
            path=Path(path)
            if path.stat().st_size>20_000_000:raise DataError('Сохранение слишком большое')
            obj=load_json(path);payload=obj['payload']
            if obj['checksum']!=fingerprint(payload) or payload['format']!='god-world':raise DataError('god save: неверный формат или контрольная сумма')
            scratch=copy.deepcopy(payload['state']);notice=''
            if payload['schema'] in (1,2) and payload['rules'] in (LEGACY_RULES,RULES_081):
                expected=LEGACY_RULES if payload['schema']==1 else RULES_081
                old_data=previous_data(self.data,payload['schema'])
                if payload['rules']!=expected or fingerprint(old_data)!=expected:raise DataError('Перенос доступен только для штатных правил 0.8.0/0.8.1')
                validate_state(scratch,old_data,legacy=payload['schema'])
                if payload['schema']==1:
                    for c in scratch['cohorts']:living.initialize(c,scratch['week'])
                    agents.initialize(scratch)
                civic.initialize(scratch,self.data);civic.evaluate_institutions(scratch,self.data,event,False);scratch['schema']=SCHEMA
                notice='Мир перенесён в 0.8.5. Старые данные и seed сохранены; учреждения и новые процессы инициализированы без выдуманного прошлого. Оплаченные проекты продолжаются без повторного списания бюджета. Сохраните под новым именем; обратной совместимости нет.'
            elif payload['schema']!=SCHEMA or payload['rules']!=fingerprint(self.data):raise DataError('god save: неподдерживаемая схема или правила')
            validate_state(scratch,self.data)
        except (OSError,KeyError,TypeError,ValueError) as exc:raise DataError('Не удалось загрузить мир: '+str(exc)) from exc
        self.state=scratch;self.undo_buffer=[];self.migration_notice=notice

    def summary(self):
        s=self.state;f=forecast(s)
        return {'week':s['week'],'energy':s['energy'],'population':sum(c['population'] for c in s['cohorts']),
                'cohorts':len(s['cohorts']),'forecast':f,'next_election':s['rules'].get('next_election',s['rules']['first_election']),
                'government':[s['parties'][p]['name'] for p in s['governing']], 'editor_used':s['editor_used']}
