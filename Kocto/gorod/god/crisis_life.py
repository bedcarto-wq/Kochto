"""Collective crisis decisions, bounded mandates and real, costed responses.
Cohorts vote as represented residents; no invented individual households.
Player changes opportunities, never signs agreements for the participants.
"""
from __future__ import annotations
from ..engine import DataError,RuleError
from . import civic,living

POLICIES={'training':'Оплатить переобучение','relief':'Временная помощь семьям','conversion':'Переоборудовать производство',
 'expand':'Расширить услугу','staff':'Набрать специалистов','mutual_aid':'Соседская взаимопомощь',
 'audit':'Независимая проверка документов','mediation':'Посредничество'}
METRICS={'security':'средняя защищённость','health':'среднее здоровье','solidarity':'соседские связи'}
ACTIONS={'none':'пауза','petition':'петиция','protest':'мирное собрание','strike':'забастовка'}
LEVELS={'owner':'собственник','city':'город','region':'регион','federal':'федерация'}
EXECUTION={'executing':'исполняется','fulfilled':'исполнено','failed':'не выполнено'}
CHOICES={'jobs':('training','relief','conversion'),'services':('expand','staff','mutual_aid'),'trust':('audit','mediation','relief')}
TREASURY_UNIT=1_000_000 # model roubles across population-weighted representatives
COSTS={'training':12,'relief':8,'conversion':32,'expand':26,'staff':10,'mutual_aid':4,'audit':4,'mediation':3}
PACES={'jobs':4,'services':3,'trust':2}
EXTRA={'districts','damage','causes','trigger','assembly','offers','agreement','window','responsibility','interpretations','baseline','outcome','archive','cooldown'}

def clip(x,a=0,b=100):return max(a,min(b,x))
def cohort_index(s):return {c['id']:c for c in s['cohorts']}

def damage(s,kind):
    out={}
    for c in s['cohorts']:
        h=c['household'];d=s['districts'][c['district']]
        if kind=='jobs':v=max(0,60-d['jobs'])*1.6+(100-h['security'])*.25+h['shortage']/max(1,h['needs'])*20+min(10,h['debt']/max(1000,h['income']))-min(10,h['savings']/max(1000,h['needs']))
        elif kind=='services':v=c['service_pressure']*7+(100-d['health'])*.08
        else:v=sum(max(0,75-c['trust'][p]) for p in s['governing'])/max(1,len(s['governing']))+h['debt']/max(1,h['income'])*.3
        out[c['id']]=clip(v)
    return out

def initialize_row(s,row):
    if 'assembly' in row:return
    losses=damage(s,row['kind']);cs=cohort_index(s);affected=[cid for cid,v in losses.items() if v>=25 and cs[cid]['population']]
    districts=sorted({cs[cid]['district'] for cid in affected}) or list(s['districts'])
    row.update({'districts':districts,'damage':losses,'causes':[], 'trigger':row['last_event'],
      'assembly':{'members':{},'representative':'','mandate':'','votes':{},'support':0.0,'resources':15.0,'fatigue':0.0,'action':'none','review':s['week'],'reason':'Жители ещё не организовались'},
      'offers':[],'agreement':None,'window':{'until':s['week']+max(1,min(26,int(mean(s,'savings')/max(1000,mean(s,'needs'))))),'reason':'Оценка первоначального резерва, не запрет решений после даты'},
      'responsibility':{'owner':40 if row['kind']=='jobs' else 0,'city':35 if row['kind']=='jobs' else 70,'region':15 if row['kind']=='jobs' else 20,'federal':10},
      'interpretations':{},'baseline':{'security':mean(s,'security'),'health':mean_district(s,'health'),'ties':mean_district(s,'solidarity'),'jobs':mean_district(s,'jobs'),'debt':mean(s,'debt')},
      'outcome':'','archive':[],'cooldown':0})

def migrate(s):
    z=s['crises'];z.setdefault('boundary',{'metric':'security','floor':25});z.setdefault('boundary_history',[]);z.setdefault('memory',[]);z.setdefault('summary',[])
    for row in z['items']:initialize_row(s,row)

def mean(s,key):
    n=max(1,sum(c['population'] for c in s['cohorts']));return sum(c['household'][key]*c['population'] for c in s['cohorts'])/n

def mean_district(s,key):
    n=max(1,sum(d['population'] for d in s['districts'].values()));return sum(d[key]*d['population'] for d in s['districts'].values())/n

def log(s,row,emit,kind,text,party=''):
    e=emit(s,kind,row['id']+': '+text,row['districts'][0],row['kind'] if row['kind']!='trust' else 'rights',party,causes=[row['last_event']])
    row['last_event']=e['id'];row['archive'].append({'week':s['week'],'event':e['id'],'text':text});del row['archive'][:-24];return e

def policy_scores(c,s,kind):
    d=s['districts'][c['district']];h=c['household'];need=100-h['security']
    all_scores={'training':50+(100-d['jobs'])*.35-h['skill']*.4-(45 if 'elder' in c['tags'] else 0),
      'relief':30+need*.8+h['shortage']/max(1,h['needs'])*30,
      'conversion':40+d['pollution']*.4+(20 if 'worker' in c['tags'] else 0),
      'expand':35+c['service_pressure']*6,'staff':35+c['service_pressure']*4+(20 if 'elder' in c['tags'] else 0),
      'mutual_aid':30+d['solidarity']*.6+(15 if c['life']['action']=='community' else 0),
      'audit':40+c['attention']['rights']*.5,'mediation':45+d['solidarity']*.4-need*.2}
    return {k:all_scores[k] for k in CHOICES[kind]}

def organize(s,row,emit):
    a=row['assembly'];cs=cohort_index(s);losses=row['damage'];week=s['week'];row['members']=0
    # Actual members are capped existing residents, with resources/time prerequisites.
    if not a['members'] and week-row['born']>=2 and row['material']>=25:
        for cid,v in losses.items():
            c=cs[cid];d=s['districts'][c['district']];h=c['household']
            if v>=25 and h['free_time']>12 and d['solidarity']>25:
                count=min(c['population'],int(c['population']*min(.35,c['engagement']/250)*min(1,h['free_time']/30)))
                if count:a['members'][cid]=count
        if sum(a['members'].values())>=20:log(s,row,emit,'crisis_assembly','жители самостоятельно создали собрание; участие не означает поддержку партии')
        else:a['members']={};a['reason']='Не хватает времени, связей или участников';return
    for cid in list(a['members']):
        n=min(a['members'][cid],cs[cid]['population'])
        if a['fatigue']>75 and week%4==0:n=int(n*.9)
        if n:a['members'][cid]=n
        else:del a['members'][cid]
    n=sum(a['members'].values());row['members']=n
    if not n:a['reason']='Нет активных участников';a['representative']='';return
    avg_time=sum(cs[cid]['household']['free_time']*count for cid,count in a['members'].items())/n
    coordination=sum(e['strength']*.04 for e in s['effects'] if e['power']=='coordination' and e['until']>=week and (e['target']=='all' or e['target'] in row['districts']) and not e.get('association_id'))
    a['resources']=clip(a['resources']+avg_time*.025+coordination);a['fatigue']=clip(a['fatigue']-1-coordination)
    if not a['mandate'] or week-a['review']>=4:
        votes={k:0 for k in CHOICES[row['kind']]}
        for cid,count in a['members'].items():
            scores=policy_scores(cs[cid],s,row['kind']);votes[max(scores,key=lambda k:(scores[k],k))]+=count
        a['votes']=votes;a['mandate']=max(votes,key=lambda k:(votes[k],k));a['support']=votes[a['mandate']]/n;a['review']=week
        old=a['representative'];a['representative']=max(a['members'],key=lambda cid:(a['members'][cid]*cs[cid]['engagement'],cid))
        if old and old!=a['representative']:log(s,row,emit,'crisis_mandate','смена представителя: '+a['representative'])
    a['action']='none'
    if week%PACES[row['kind']]==0 and a['resources']>=3 and a['fatigue']<85:
        a['resources']-=3;a['fatigue']=clip(a['fatigue']+5)
        a['action']='petition' if row['material']<65 else 'protest'
        workers=sum(count for cid,count in a['members'].items() if 'worker' in cs[cid]['tags'])
        if row['kind']=='jobs' and workers/n>.5 and row['material']>75 and a['fatigue']<60:a['action']='strike'
        a['reason']='Коллективное действие по мандату: '+POLICIES[a['mandate']]
        log(s,row,emit,'crisis_action',{'petition':'петиция','protest':'мирное собрание','strike':'забастовка работников'}[a['action']]+'; ресурсы и время расходуются')
    else:a['reason']='Восстановление времени и средств; затишье не равно решению причины'

def mediator(s,row):
    candidates=[];gov=s['governing'];leaders=[s['parties'][p]['leader'] for p in gov]
    for aid,a in s['actors'].items():
        if not a['alive'] or a['role']=='leader':continue
        relations=sum(a['relations'].get(b,0) for b in leaders)/max(1,len(leaders))
        score=a['honesty']*.4+a['competence']*.2+relations*.3+(10 if a['district'] in row['districts'] else 0)
        candidates.append((score,aid))
    return max(candidates)[1] if candidates and max(candidates)[0]>=35 else ''

def offer(s,data,row,emit):
    a=row['assembly'];week=s['week'];n=sum(a['members'].values())
    if not n or row['agreement'] or week<row['cooldown'] or week%PACES[row['kind']]:return
    cs=cohort_index(s)
    known_count=sum(count for cid,count in a['members'].items() if row['trigger'] in cs[cid]['known'] or row['last_event'] in cs[cid]['known'])
    if known_count/n<.1:a['reason']='Обсуждение ещё не достигло сторон';return
    pid=s['governing'][0] if s['governing'] else ''
    if not pid:return
    p=s['parties'][pid];actor=s['actors'][p['leader']]
    if not actor['alive'] or p['funds']<1:return
    # No reads of unknown residents' exact utilities by politician: observed sample only.
    observed=[cs[cid] for cid in a['members'] if row['trigger'] in cs[cid]['known']][:24]
    scores={k:sum(policy_scores(c,s,row['kind'])[k] for c in observed)/max(1,len(observed)) + actor['competence']*.1 - COSTS[k]*.5 for k in CHOICES[row['kind']]}
    if row['kind']=='jobs':scores['relief']+=max(0,-p['ideology']['economy'])*.15;scores['conversion']+=max(0,p['ideology']['ecology'])*.2
    for prior in row['offers'][-3:]:
        if not prior['accepted']:scores[prior['policy']]-=18 # learn from actual refusal, not read all minds
    selected=max(scores,key=lambda k:(scores[k],k));p['funds']-=1
    voters={cid:policy_scores(cs[cid],s,row['kind']) for cid in a['members']}
    yes=sum(count for cid,count in a['members'].items() if voters[cid][selected]>=max(voters[cid].values())*.9)
    share=yes/n;mediator_id=mediator(s,row)
    # Mediator offers a chance of a bounded compromise, never a signature for everyone.
    threshold=.6 if not mediator_id else .55
    reason='Мандат не позволяет принять предложение' if share<threshold else 'Согласие участников получено; проверяются полномочия и ресурсы'
    rec={'week':week,'party':pid,'policy':selected,'yes':yes,'total':n,'share':share,'mediator':mediator_id,'accepted':False,'reason':reason,'event':0}
    row['offers'].append(rec);del row['offers'][:-8];row['cooldown']=week+PACES[row['kind']]
    for q,party in s['parties'].items():
        if party['active']:row['interpretations'][q]={'week':week,'known':known_count,'total':n,'claim':'несправедливое распределение' if party['ideology']['economy']<0 else 'ограничения ресурсов' if party['ideology']['economy']>20 else 'ответственность управления','sample':len(observed)}
    row['interpretations'][pid]={'week':week,'known':known_count,'total':n,'claim':'материальная нужда' if p['ideology']['economy']<0 else 'возможности хозяйства','sample':len(observed)}
    if share<threshold:
        rec['event']=log(s,row,emit,'crisis_refusal','предложение '+POLICIES[selected]+' отвергнуто: '+str(round(share*100))+'% участников; '+reason,pid)['id'];return
    cost=COSTS[selected];did=max(row['districts'],key=lambda d:sum(row['damage'][cid]*c['population'] for cid,c in cs.items() if c['district']==d))
    if s['budget']<cost:rec['reason']='Муниципалитет отвечает, но в казне не хватает средств';return
    if selected=='conversion' and (s['firms'][did]['capital']<25 or s['districts'][did]['infra']<60 or actor['competence']<45 or (s['story'] and did=='factory')):
        rec['reason']='Собственник не согласен или отсутствуют инфраструктура/компетентность; сценарный комбинат решается отдельно';return
    if selected=='expand':
        inst=max((i for i in s['civic']['institutions'].values() if i['district']==did),key=lambda i:i['delay'])
        project=civic.propose(s,data,pid,inst['id'],emit,row['last_event'])
        if not project:project=next((p for p in s['projects'] if p['institution']==inst['id'] and p['party']==pid and p['stage'] not in ('operating','rejected')),None)
        if not project:rec['reason']='Нет доступного согласованного проекта этой стороны';return
        # civic.project_tick owns the payment. No double charge or parallel facility rules.
        agreement={'policy':selected,'party':pid,'district':did,'cost':0.0,'pool':0.0,'spent':0.0,'due':week+10,'progress':0,'status':'executing','project':project['id'],'event':0,'start':week,'promised':cost,'benefit':0.0,'returned':0.0,'condition':'Оплата и исполнение обычного проекта; наличие персонала'}
    else:
        s['budget']-=cost
        agreement={'policy':selected,'party':pid,'district':did,'cost':float(cost),'pool':float(cost) if selected in ('training','relief') else 0.0,'spent':0.0,'due':week+9,'progress':0,'status':'executing','project':'','event':0,'start':week,'promised':cost,'benefit':0.0,'returned':0.0,'condition':'Сохранять средства и доступ; исполнение может задержаться'}
    rec['accepted']=True;rec['reason']='Соглашение принято самими сторонами, результат ещё не достигнут';row['agreement']=agreement
    agreement['event']=log(s,row,emit,'crisis_agreement','принято '+POLICIES[selected]+'; расходы '+str(cost)+'; срок '+str(agreement['due'])+'; '+agreement['condition'],pid)['id'];rec['event']=agreement['event']
    if selected not in ('training','relief','expand'):agreement['spent']=float(cost)

def subsidy(s,c):
    """Read this week's preallocated escrow; no iteration-order-dependent spending."""
    return sum(row['agreement'].get('payments',{}).get(c['id'],0.0) for row in s['crises']['items'] if row.get('agreement'))


def labour_factor(s,c):
    factor=1.0
    if 'worker' not in c['tags']:return factor
    for row in s['crises']['items']:
        a=row.get('assembly',{})
        if a.get('action')=='strike':factor-=a.get('members',{}).get(c['id'],0)/max(1,c['population'])*.5
    return max(.7,factor)

def execute(s,data,row,emit):
    ag=row['agreement']
    if not ag or ag['status']!='executing':return
    did=ag['district'];d=s['districts'][did];policy=ag['policy'];week=s['week'];cs=cohort_index(s)
    available=d['access']>45 and d['weather']<15
    if policy=='expand':
        p=next((p for p in s['projects'] if p['id']==ag['project']),None)
        if p and p['stage']=='operating':ag['status']='fulfilled';ag['benefit']=p['gain'];ag['spent']=p['spent']
        elif not p or p['stage']=='rejected':ag['status']='failed'
    elif policy=='training':
        if available:
            for cid in row['assembly']['members']:
                c=cs[cid]
                scores=policy_scores(c,s,'jobs')
                willing=scores['training']>=max(scores.values())*.9
                if willing and 'elder' not in c['tags'] and c['household']['security']>20 and c['life']['completed']==0 and c['household']['skill']<40:
                    c['life'].update(action='study',remaining=max(1,8-c['household']['training']))
            ag['progress']+=1
        if ag['progress']>=9:ag['status']='fulfilled';ag['benefit']=sum(cs[cid]['life']['completed']>0 for cid in row['assembly']['members'])
    elif policy=='relief':
        ag['progress']+=1
        if ag['progress']>=9:ag['status']='fulfilled';ag['benefit']=ag['spent']
    elif available:
        ag['progress']+=1
        if policy=='mutual_aid':d['solidarity']=clip(d['solidarity']+.6);d['health']=clip(d['health']+.15)
        elif policy=='staff':
            for i in s['civic']['institutions'].values():
                if i['district']==did:i['staff']=clip(i['staff']+.8)
        elif policy=='audit':
            # Evidence must be related to this place and independent actual documents.
            docs=[doc for doc in s['civic']['documents'] if doc['district']==did]
            for doc in docs:doc['access']=min(1,doc['access']+.04)
            if len({doc['kind'] for doc in docs})>=2:ag['benefit']=len(docs)
        elif policy=='mediation':
            mid=mediator(s,row)
            if mid:
                for leader in (s['parties'][p]['leader'] for p in s['governing']):
                    s['actors'][mid]['relations'][leader]=clip(s['actors'][mid]['relations'].get(leader,0)+1,-100,100)
                d['solidarity']=clip(d['solidarity']+.2)
        if ag['progress']>=6:
            if policy=='conversion':
                firm=s['firms'][did];firm['capital']=clip(firm['capital']-12);firm['workers']+=40;d['jobs']=clip(d['jobs']+5);d['pollution']=clip(d['pollution']-8);ag['benefit']=40
            ag['status']='fulfilled' if policy!='audit' or ag['benefit'] else 'failed'
    if week>ag['due']+8 and ag['status']=='executing':ag['status']='failed'
    if ag['status']!='executing':
        # Return unused escrow. Promise failures do not delete paid expenditure.
        if ag['pool']>0:
            returned=min(ag['pool'],300-s['budget']);s['budget']+=returned;ag['pool']-=returned;ag['returned']+=returned
        log(s,row,emit,'crisis_delivery','соглашение '+('исполнено' if ag['status']=='fulfilled' else 'не выполнено')+'; списано '+str(round(ag['spent'],2))+'; улучшение не означает устранение причины',ag['party'])

def update(s,data,row,emit):
    initialize_row(s,row);row['damage']=damage(s,row['kind']);row['districts']=sorted({c['district'] for c in s['cohorts'] if row['damage'][c['id']]>=25 and c['population']}) or row['districts']
    if not row['causes']:
        relevant=[e for e in s['events'] if e['id']<row['trigger'] and e['district'] in row['districts'] and e['kind'] in ('overload','employer','household','promise_broken','crisis')]
        row['causes']=[e['id'] for e in relevant[-6:]]
    if row['stage']=='resolved':
        if not row['outcome']:
            before=row['baseline'];ag=row['agreement'];row['outcome']='устранение давления' if row['material']<10 else 'адаптация к потерям'
            if ag and ag['status']=='fulfilled':row['outcome']='устойчивое исполнение соглашения'
            metric=s['crises']['boundary']['metric'];floor=s['crises']['boundary']['floor'];current=mean(s,metric) if metric=='security' else mean_district(s,metric)
            row['epilogue']=[row['id']+': '+row['outcome']+'. Обязательство: '+__import__(__package__+'.crises',fromlist=['GOALS']).GOALS.get(s['crises']['goal'],'не принято'),
              'Защищённость '+str(round(before['security']))+' → '+str(round(mean(s,'security')))+'; здоровье '+str(round(before['health']))+' → '+str(round(mean_district(s,'health')))+'; долг '+str(round(before['debt']))+' → '+str(round(mean(s,'debt'))),
              'Граница '+METRICS[metric]+' ≥ '+str(floor)+': '+('сохранена' if current>=floor else 'нарушена')+'. Первоначальные обязательства и отказы остаются в истории.']
            s['crises']['memory'].append({'kind':row['kind'],'ended':s['week'],'outcome':row['outcome'],'districts':row['districts'],'delivery':bool(ag and ag['status']=='fulfilled')});del s['crises']['memory'][:-24]
            row['assembly']['action']='none'
        return
    ag=row['agreement']
    if ag and ag['status']!='executing' and not ag['pool'] and s['week']>ag['due']+8:
        log(s,row,emit,'crisis_reassessment','причина остаётся после прежнего соглашения; стороны могут пересмотреть ответ');row['agreement']=None
    organize(s,row,emit);offer(s,data,row,emit)
    # Lasting hardship transfers the same conflict to the responsibility domain, preserving origins.
    if s['week']-row['born']>=12 and row['material']>60 and row['agreement'] and row['agreement']['status']=='failed':
        for c in s['cohorts']:
            if c['id'] in row['assembly']['members']:
                for pid in s['governing']:c['trust'][pid]=clip(c['trust'][pid]-.08)
    # Past successful cooperation raises resources, not direct popularity or guaranteed acceptance.
    if s['week']==row['born']+2 and any(m['kind']==row['kind'] and m['delivery'] for m in s['crises']['memory']):row['assembly']['resources']=clip(row['assembly']['resources']+2)

def before(s,data,emit):
    for row in s['crises']['items']:
        if 'agreement' not in row:continue
        cs=cohort_index(s);a=row['assembly']
        a['members']={cid:min(n,cs[cid]['population']) for cid,n in a['members'].items() if cs[cid]['population']}
        if a['members'] and a['representative'] not in a['members']:a['representative']=max(a['members'],key=a['members'].get)
        row['members']=sum(a['members'].values())
        execute(s,data,row,emit);ag=row['agreement']
        if not ag:continue
        ag['payments']={}
        if ag['status']!='executing' or ag['policy'] not in ('training','relief') or ag['pool']<=0:continue
        eligible=[c for c in s['cohorts'] if c['id'] in row['assembly']['members'] and c['population'] and (ag['policy']=='relief' or c['life']['action']=='study')]
        population=sum(c['population'] for c in eligible)
        if population:
            spent=min(ag['cost']/8,ag['pool']);grant=spent*TREASURY_UNIT/population
            ag['payments']={c['id']:grant for c in eligible};ag['pool']-=spent;ag['spent']+=spent


def boundary(s,value,emit):
    if not isinstance(value,dict) or set(value)!={'metric','floor'} or value['metric'] not in ('security','health','solidarity') or type(value['floor']) not in (int,float) or not 0<=value['floor']<=100:raise RuleError('Граница: защищённость, здоровье или связи; порог 0–100')
    z=s['crises'];z['boundary_history'].append({'week':s['week'],'old':dict(z['boundary']),'new':dict(value)});del z['boundary_history'][:-24];z['boundary']=dict(value);emit(s,'crisis_boundary','Игрок пересмотрел недопустимую потерю: '+value['metric']+' < '+str(value['floor']));s['revision']+=1

def describe(s,row):
    a=row['assembly'];cs=cohort_index(s);top=sorted(row['damage'],key=lambda cid:(-row['damage'][cid],cid))[:4]
    lines=['Причины #'+', #'.join(map(str,row['causes']))+'; повод #'+str(row['trigger']),
      'Места: '+', '.join(s['districts'][d]['name'] for d in row['districts']),
      'Ответственность модели: '+', '.join(LEVELS[k]+' '+str(v)+'%' for k,v in row['responsibility'].items())+'; это полномочия/вклад, не убеждение жителей.',
      'Затронутые когорты: '+', '.join(cid+' / '+s['districts'][cs[cid]['district']]['name']+' / '+('родители' if 'parent' in cs[cid]['tags'] else 'одинокие')+' / '+('пенсионеры' if 'elder' in cs[cid]['tags'] else 'студенты' if 'student' in cs[cid]['tags'] else 'работающие')+' (ущерб '+str(round(row['damage'][cid]))+', '+str(cs[cid]['population'])+' жителей)' for cid in top),
      'Собрание: '+str(sum(a['members'].values()))+' участников; представитель '+(a['representative'] or 'не выбран'),
      'Мандат: '+POLICIES.get(a['mandate'],'нет')+'; поддержка '+str(round(a['support']*100))+'%; '+a['reason'],
      'Ресурсы '+str(round(a['resources']))+'; усталость '+str(round(a['fatigue']))+'; действие '+ACTIONS[a['action']],
      'Оценка первоначального резерва: до недели '+str(row['window']['until'])+'. Это не точный прогноз и не запрет решения после даты.']
    for o in row['offers'][-3:]:lines.append('Предложение '+POLICIES[o['policy']]+' — '+str(round(o['share']*100))+'%: '+o['reason'])
    ag=row['agreement']
    if ag:lines.append('Соглашение: '+POLICIES[ag['policy']]+'; '+EXECUTION[ag['status']]+'; срок '+str(ag['due'])+'; списано '+str(round(ag['spent'],2))+'; резерв '+str(round(ag['pool'],2)))
    lines+=row['epilogue'];return lines

def validate(s,numeric):
    z=s['crises'];numeric(z['boundary']['floor'],0,100,'crisis boundary')
    if set(z['boundary'])!={'metric','floor'} or z['boundary']['metric'] not in ('security','health','solidarity') or len(z['memory'])>24 or len(z['boundary_history'])>24 or len(z['summary'])>3:raise DataError('crisis life: limits')
    cs=cohort_index(s)
    for r in z['items']:
        if not EXTRA<=set(r) or not r['districts'] or any(d not in s['districts'] for d in r['districts']) or set(r['damage'])!=set(cs) or len(r['causes'])>6 or len(r['archive'])>24 or len(r['offers'])>8:raise DataError('crisis life: references')
        for v in r['damage'].values():numeric(v,0,100,'crisis damage')
        a=r['assembly']
        if set(a)!={'members','representative','mandate','votes','support','resources','fatigue','action','review','reason'} or not isinstance(a['members'],dict) or set(a['votes'])-set(CHOICES[r['kind']]) or any(type(n) is not int or n<0 for n in a['votes'].values()) or type(a['review']) is not int or not 1<=a['review']<=s['week']:raise DataError('crisis life: assembly schema')
        numeric(a['resources'],0,100,'assembly resources');numeric(a['fatigue'],0,100,'assembly fatigue');numeric(a['support'],0,1,'mandate')
        if any(cid not in cs or type(n) is not int or not 0<n<=cs[cid]['population'] for cid,n in a['members'].items()) or (a['members'] and a['representative'] not in a['members']) or a['action'] not in ('none','petition','protest','strike'):raise DataError('crisis life: membership')
        if a['mandate'] and a['mandate'] not in CHOICES[r['kind']]:raise DataError('crisis life: mandate')
        for offer in r['offers']:
            if offer['party'] not in s['parties'] or offer['policy'] not in CHOICES[r['kind']] or type(offer['accepted']) is not bool or not 0<=offer['yes']<=offer['total']:raise DataError('crisis life: offer')
            numeric(offer['share'],0,1,'offer support')
        ag=r['agreement']
        if ag:
            if ag['policy'] not in CHOICES[r['kind']] or ag['party'] not in s['parties'] or ag['district'] not in s['districts'] or ag['status'] not in ('executing','fulfilled','failed'):raise DataError('crisis life: agreement')
            payments=ag.get('payments',{})
            if not isinstance(payments,dict) or any(cid not in cs for cid in payments) or type(ag['progress']) is not int or not 0<=ag['progress']<=104 or type(ag['due']) is not int or ag['due']<ag['start']:raise DataError('crisis life: payment or timeline')
            for v in payments.values():numeric(v,0,300*TREASURY_UNIT,'crisis income')
            for k in ('cost','pool','spent','returned'):numeric(ag[k],0,300,'crisis escrow')
            if ag['policy'] in ('training','relief') and abs(ag['pool']+ag['spent']+ag['returned']-ag['cost'])>1e-6:raise DataError('crisis life: unbalanced escrow')
