"""Bounded material crises; peaceful organization is not a failure condition."""
from ..engine import DataError,RuleError
from . import civic,crisis_life
KINDS={'jobs':'Потеря заработка','services':'Недоступность услуг','trust':'Кризис ответственности'}
STAGES={'warning':'ранние признаки','organizing':'жители организуются','negotiating':'поиск решения','acute':'острая фаза','recovering':'восстановление','resolved':'завершён'}
GOALS={'livelihood':'Сохранить средства к жизни','access':'Восстановить доступ к помощи','ties':'Сохранить возможность сотрудничества','observe':'Оставить решение людям'}

def initialize(s):
    s['crises']={'items':[],'next_id':1,'goal':None,'history':[]}
    crisis_life.migrate(s)

def measures(s,kind):
    ds=list(s['districts'].values());cs=s['cohorts'];n=max(1,sum(c['population'] for c in cs))
    if kind=='jobs':material=sum(max(0,60-d['jobs'])*2*d['population'] for d in ds)/n
    elif kind=='services':material=sum(c['service_pressure']*7*c['population'] for c in cs)/n
    else:material=sum(max(0,75-sum(c['trust'][p] for p in s['governing'])/max(1,len(s['governing'])))*c['population'] for c in cs)/n
    capacity=min(100,s['budget']/3+sum(d['solidarity'] for d in ds)/len(ds)*.4)
    division=min(100,sum(c['stress']*c['population'] for c in cs)/n*.55+material*.3)
    return min(100,max(0,material)),capacity,division

def tick(s,data,emit):
    z=s['crises'];week=s['week']
    for kind in KINDS:
        material,capacity,division=measures(s,kind)
        losses=crisis_life.damage(s,kind)
        worst=max(sum(losses[c['id']]*c['population'] for c in s['cohorts'] if c['district']==did)/max(1,d['population']) for did,d in s['districts'].items())
        material=max(material,worst*.75)
        row=next((c for c in z['items'] if c['kind']==kind and c['stage']!='resolved'),None)
        if row is None and material>=data['scale_rules']['crisis_trigger']:
            cid='K'+str(z['next_id']);z['next_id']+=1
            e=emit(s,'crisis_warning',cid+': '+KINDS[kind]+' — признаки устойчивой проблемы',topic=kind if kind!='trust' else 'rights')
            row={'id':cid,'kind':kind,'stage':'warning','material':material,'capacity':capacity,'division':division,'born':week,'low_weeks':0,'peak':material,'last_event':e['id'],'response_week':0,'epilogue':[],'members':0};z['items'].append(row)
        if row is None:continue
        old=row['stage'];row.update(material=material,capacity=capacity,division=division);row['peak']=max(row['peak'],material)
        row['low_weeks']=row['low_weeks']+1 if material<20 else 0
        if row['low_weeks']>=4:
            row['stage']='resolved';row['epilogue']=[KINDS[kind]+': материальное давление снижено четыре недели подряд.','Пик '+str(round(row['peak']))+' → '+str(round(material))+'. Восстановление не стирает долги и прежние потери.','Обязательство: '+GOALS.get(z['goal'],'не принято')+'. Точный вклад отдельного вмешательства не рассчитан.']
        elif row['low_weeks']>0:row['stage']='recovering'
        elif week-row['born']>=3:
            solidarity=sum(d['solidarity'] for d in s['districts'].values())/4
            row['members']=min(n:=sum(c['population'] for c in s['cohorts']),int(n*solidarity/1000))
            row['stage']='acute' if material>=65 and capacity<40 else 'negotiating' if capacity>=45 else 'organizing'
        else:row['stage']='warning'
        # Existing institutions and actual budgets decide the response, not a scripted victory.
        if kind=='services' and row['stage'] in ('negotiating','acute') and week-row['response_week']>=8 and s['governing']:
            pid=s['governing'][0];actor=s['actors'][s['parties'][pid]['leader']]
            if actor['alive'] and actor['competence']>=45:
                inst=max(s['civic']['institutions'].values(),key=lambda i:i['delay'])
                p=civic.propose(s,data,pid,inst['id'],emit,row['last_event'])
                if p:row['response_week']=week
        crisis_life.update(s,data,row,emit)
        if row['stage']!=old:
            e=emit(s,'crisis_phase',row['id']+': '+STAGES[row['stage']]+'; давление '+str(round(material))+', способность решать '+str(round(capacity)),topic=kind if kind!='trust' else 'rights',causes=[row['last_event']]);row['last_event']=e['id']
    z['summary']=[r['id']+': '+STAGES[r['stage']]+'; давление '+str(round(r['material']))+'; '+r['assembly']['reason'] for r in z['items'] if r['stage']!='resolved'][:3]
    active=[c for c in z['items'] if c['stage']!='resolved'];ended=[c for c in z['items'] if c['stage']=='resolved'][-12:];z['items']=active+ended

def choose(s,value,emit):
    if value not in GOALS:raise RuleError('Неизвестное обязательство кризиса')
    z=s['crises'];z['history'].append({'week':s['week'],'old':z['goal'],'new':value});del z['history'][:-24];z['goal']=value
    emit(s,'crisis_commitment','Обязательство игрока: '+GOALS[value]);s['revision']+=1

def validate(s,numeric):
    z=s['crises']
    if set(z)!={'items','next_id','goal','history','boundary','boundary_history','memory','summary'} or z['goal'] not in (None,*GOALS) or type(z['next_id']) is not int or z['next_id']<1 or len(z['items'])>15 or len(z['history'])>24:raise DataError('crises: schema')
    ids=set()
    for c in z['items']:
        if c['id'] in ids or c['kind'] not in KINDS or c['stage'] not in STAGES or type(c['born']) is not int or c['born']<1 or type(c['low_weeks']) is not int or c['low_weeks']<0 or type(c['members']) is not int or c['members']<0:raise DataError('crises: state')
        ids.add(c['id'])
        for k in ('material','capacity','division','peak'):numeric(c[k],0,100,'crisis '+k)
        if len(c['epilogue'])>3 or any(not isinstance(t,str) for t in c['epilogue']):raise DataError('crises: epilogue')

    crisis_life.validate(s,numeric)
