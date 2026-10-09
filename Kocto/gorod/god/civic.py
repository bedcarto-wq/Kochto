"""Capacity, civic organizations, staged public works and documentary evidence.
Bounded deterministic aggregate model. Opportunities never force agreement.
"""
from __future__ import annotations
import math
from ..engine import RuleError,DataError

KINDS={'clinic':'Больница','school':'Школа','transport':'Транспорт'}
STAGES={'proposed':'предложен','approved':'согласован','funded':'профинансирован','building':'выполняется','staffing':'набор персонала','operating':'работает','rejected':'отклонён'}
REACTIONS={'support':'поддержать требование','alternative':'предложить иной путь','claim':'приписать себе заслугу','ignore':'не вмешиваться'}
NEW_POWERS={'encounter','discovery','free_time','coordination'}

def clip(x,a=0,b=100):return max(a,min(b,x))

def initialize(s,data):
    if 'civic' in s:return
    z={'institutions':{},'associations':[],'documents':[],'cases':[],'meetings':[],'causal':[], 'changes':[],
       'next_project':1,'next_document':1,'next_association':1,'next_case':1}
    s['civic']=z
    cfg=data['civic']
    for did,d in s['districts'].items():
        for kind in KINDS:
            iid=did+':'+kind;capacity=d['population']*cfg['demand'][kind]*(.65+d['infra']/200)
            z['institutions'][iid]={'id':iid,'district':did,'kind':kind,'capacity':capacity,'staff':clip(45+d['jobs']*.35),
                'condition':d['infra'],'demand':0.0,'served':0.0,'queue':0.0,'delay':0.0,'cause':0,'last_notice':0}
    # Paid legacy projects continue without charging their old budget twice.
    for p in s['projects']:
        p.update({'id':'w'+str(z['next_project']),'institution':'','stage':'building','due':max(s['week'],p['finish']),
            'cost':22.0,'spent':22.0,'progress':0.0,'proposal_event':0,'last_event':0,'public_open':False,'completed':0,'recruited':0.0})
        z['next_project']+=1
    for c in s['cohorts']:c['service_pressure']=0.0;c['service_cause']=0


def archive(s,e):
    if 'civic' not in s:return
    s['civic']['causal'].append({k:e[k] for k in ('id','week','kind','party','causes')}|{'text':e['text'][:240]})
    del s['civic']['causal'][:-900]


def ancestry(s,eid,limit=20):
    index={e['id']:e for e in s['civic']['causal']};seen=set();out=[]
    def visit(key,depth):
        if key in seen or len(out)>=limit:return
        seen.add(key);node=index.get(key)
        if not node:out.append({'id':key,'depth':depth,'text':'Причина за пределами сохранённого архива','missing':True});return
        out.append({'id':key,'depth':depth,'text':node['text'],'missing':False})
        for parent in node['causes']:visit(parent,depth+1)
    visit(eid,0);return out


def document(s,kind,project,emit,published=False):
    z=s['civic'];did='D'+str(z['next_document']);z['next_document']+=1
    # Snapshot, not a mutable narration that rewrites past facts.
    doc={'id':did,'week':s['week'],'kind':kind,'project':project['id'],'party':project['party'],
         'district':project['district'],'cost':project['cost'],'stage':project['stage'],'spent':project['spent'],'progress':project['progress'],
         'public_open':project['public_open'],'published':published,'access':.35 if published else .08,
         'event':project['last_event'],'checked':False}
    z['documents'].append(doc);del z['documents'][:-192]
    return doc


def evaluate_institutions(s,data,emit,announce=True):
    cfg=data['civic']
    for i in s['civic']['institutions'].values():
        d=s['districts'][i['district']];local=[c for c in s['cohorts'] if c['district']==i['district']]
        if i['kind']=='school':demand=sum(c['population']*(.65 if 'parent' in c['tags'] else .08) for c in local)
        elif i['kind']=='clinic':demand=sum(c['population']*(.30 if 'elder' in c['tags'] else .14)*(1+(100-d['health'])/150) for c in local)
        else:demand=sum(c['population']*(.40 if 'elder' in c['tags'] else .8) for c in local)
        i['demand']=demand;i['condition']=clip(i['condition']-.08-.02*max(0,d['weather'])+.02*(d['infra']-i['condition']) if announce else i['condition'])
        effective=i['capacity']*(i['staff']/100)*(.4+.6*i['condition']/100)
        i['served']=min(demand,effective);i['queue']=max(0,demand-effective)
        i['delay']=clip(i['queue']/max(1,effective)*4,0,20)
        if announce and i['delay']>1 and (i['last_notice']==0 or s['week']-i['last_notice']>=8):
            e=emit(s,'overload',KINDS[i['kind']]+' / '+d['name']+': нагрузка превышает доступное обслуживание; задержка '+str(round(i['delay'],1)),i['district'],'services',causes=[i['cause']] if i['cause'] else [])
            i['cause']=e['id'];i['last_notice']=s['week']
    for c in s['cohorts']:
        rows=[i for i in s['civic']['institutions'].values() if i['district']==c['district']]
        relevant=[i for i in rows if i['kind']!='school' or 'parent' in c['tags'] or 'student' in c['tags']]
        pressure=sum(i['delay'] for i in relevant)/max(1,len(relevant));c['service_pressure']=pressure
        worst=max(relevant,key=lambda x:x['delay']);c['service_cause']=worst['cause']
        if announce:
            c['stress']=clip(c['stress']+pressure*.12);c['attention']['services']=clip(c['attention']['services']+pressure*.45)
            c['household']['free_time']=clip(c['household']['free_time']-pressure*.4)
            for pid in s['governing']:c['trust'][pid]=clip(c['trust'][pid]-min(.15,pressure*.012)/max(1,len(s['governing'])))


def associations(s,data,rng,emit):
    z=s['civic']
    for i in z['institutions'].values():
        current=next((g for g in z['associations'] if g['institution']==i['id'] and g['active']),None)
        local=[c for c in s['cohorts'] if c['district']==i['district'] and c['population']]
        if not current and i['delay']>1.5 and s['week']%4==0 and s['districts'][i['district']]['solidarity']>25:
            members={c['id']:int(c['population']*min(.4,c['engagement']/250)*(.8 if i['kind']!='school' or 'parent' in c['tags'] else .15)) for c in local}
            members={k:v for k,v in members.items() if v>0}
            if sum(members.values())<20:continue
            leader=max(members,key=lambda k:(members[k],k));gid='G'+str(z['next_association']);z['next_association']+=1
            e=emit(s,'civic_group','Жители создали '+gid+': объединение за доступность '+KINDS[i['kind']].lower(),i['district'],'services',causes=[i['cause']] if i['cause'] else [])
            current={'id':gid,'institution':i['id'],'district':i['district'],'members':members,'leader':leader,
                'resources':20.0,'fatigue':0.0,'demand':max(.25,i['delay']*.65),'active':True,'born':s['week'],'cause':e['id'],'origin':e['id'],
                'positions':{},'stances':{},'last_action':s['week'],'leadership_review':s['week']}
            z['associations'].append(current)
        if not current:continue
        g=current
        # People are a subset of existing cohort residents, never new population.
        for cid in list(g['members']):
            c=next(c for c in s['cohorts'] if c['id']==cid);g['members'][cid]=min(g['members'][cid],c['population'])
            if g['members'][cid]==0:del g['members'][cid]
        if not g['members']:g['active']=False;continue
        if g['leader'] not in g['members']:g['leader']=max(g['members'],key=g['members'].get)
        g['resources']=clip(g['resources']+sum(next(c for c in s['cohorts'] if c['id']==cid)['household']['free_time']*n for cid,n in g['members'].items())/max(1,sum(g['members'].values()))*.018)
        boost=0.0
        from .world import affected
        for eff in s['effects']:
            if eff['power']!='coordination' or eff['until']<s['week'] or (eff.get('association_id') and eff['association_id']!=g['id']):continue
            ids={c['id'] for c in affected(s,eff['target'])}
            share=sum(n for cid,n in g['members'].items() if cid in ids)/max(1,sum(g['members'].values()))
            boost+=eff['strength']*.04*share
        needed=max(1,4-boost)
        if s['week']%4==0 and g['resources']>=needed and g['fatigue']<85 and i['delay']>g['demand']:
            g['resources']-=needed;g['fatigue']=clip(g['fatigue']+6-boost)
            e=emit(s,'petition',g['id']+' требует снизить задержку обслуживания до '+str(round(g['demand'],1)),g['district'],'services',causes=[g['cause'],i['cause']])
            g['cause']=e['id'];g['last_action']=s['week']
        else:g['fatigue']=clip(g['fatigue']-1-boost)
        if i['delay']<=g['demand']:
            g['active']=False;emit(s,'civic_success',g['id']+' снижает активность: доступность услуги действительно улучшилась',g['district'],'services',causes=[g['cause'],i['cause']])
        elif g['fatigue']>70 and s['week']%8==0:
            for cid in g['members']:g['members'][cid]=max(0,int(g['members'][cid]*.9))
        if s['week']-g['leadership_review']>=12:
            choices={cid:n*next(c for c in s['cohorts'] if c['id']==cid)['engagement'] for cid,n in g['members'].items()}
            leader=max(choices,key=lambda k:(choices[k],k));g['leadership_review']=s['week']
            if leader!=g['leader']:
                g['leader']=leader;emit(s,'civic_election',g['id']+' выбрало нового представителя когорты '+leader,g['district'],'services',causes=[g['cause']])
    # Keep active and recent ended groups. Maximum possible active groups: 12.
    inactive=[g for g in z['associations'] if not g['active']][-24:]
    z['associations']=[g for g in z['associations'] if g['active']]+inactive


def propose(s,data,pid,iid,emit,cause=0,alternative=False):
    z=s['civic']
    if iid not in z['institutions']:raise RuleError('Неизвестное учреждение')
    if len(s['projects'])>=24:return None
    if any(p.get('institution')==iid and p.get('stage') not in ('operating','rejected') for p in s['projects']):return None
    i=z['institutions'][iid];p=s['parties'][pid];cost=data['civic']['project_cost']*(.65 if alternative else 1)
    # No promise of an impossible unbounded capacity gain.
    project={'id':'w'+str(z['next_project']),'party':pid,'district':i['district'],'institution':iid,'field':'infra','topic':'services',
        'started':s['week'],'finish':s['week']+8,'quality':p['competence'],'gain':i['capacity']*(.125 if alternative else .25),'stage':'proposed','due':s['week']+1,
        'cost':cost,'spent':0.0,'progress':0.0,'proposal_event':0,'last_event':0,'public_open':False,'completed':0,'recruited':i['staff']}
    z['next_project']+=1
    e=emit(s,'proposal',p['name']+' предлагает расширить '+KINDS[i['kind']].lower()+' / '+s['districts'][i['district']]['name']+'; стоимость '+str(round(cost,1)),i['district'],'services',pid,[cause] if cause else [])
    project['proposal_event']=e['id'];project['last_event']=e['id'];s['projects'].append(project);document(s,'proposal',project,emit,True)
    return project


def political_response(s,data,pid,rng,emit):
    p=s['parties'][pid];a=s['actors'][p['leader']];z=s['civic']
    known={eid for c in s['cohorts'] if c['district']==a['district'] for eid in c['known']}
    groups=[g for g in z['associations'] if g['active'] and (g['origin'] in known or g['cause'] in known)]
    if not groups:return
    g=max(groups,key=lambda x:sum(x['members'].values()));old=g['positions'].get(pid)
    if old and s['week']-old['week']<9:return
    aligned=100-abs(p['ideology']['economy']+35)/2
    rows={'support':30+aligned*.3+a['honesty']*.2+(15 if pid in s['governing'] else -10),
          'alternative':35+a['competence']*.25+(100-aligned)*.2,'claim':20+(100-a['honesty'])*.45,'ignore':25+(100-p['funds'])*.1}
    if p['funds']<3:reaction='ignore'
    else:reaction=max(rows,key=lambda k:(rows[k],k));p['funds']-=3
    # Members judge offers independently; support is not an endorsement of the party.
    attitude=clip(aligned*.5+a['honesty']*.4-g['fatigue']*.2+(10 if reaction=='support' else -15 if reaction=='claim' else -5),-100,100)
    previous={'event':old['event'],'stance':g['stances'].get(pid,0)} if old else {'event':0,'stance':0}
    g['stances'][pid]=attitude;g['positions'][pid]={'reaction':reaction,'week':s['week'],'score':rows[reaction],'event':0,'previous':previous}
    e=emit(s,'civic_response',p['name']+' решает '+REACTIONS[reaction]+' '+g['id']+'; отношение участников '+str(round(attitude)),g['district'],'services',pid,[g['cause']])
    g['positions'][pid]['event']=e['id']
    if reaction in ('support','alternative'):
        # Alternatives are a smaller staffing effort, not a fictitious full construction.
        project=propose(s,data,pid,g['institution'],emit,e['id'],reaction=='alternative')


def project_tick(s,data,rng,emit):
    z=s['civic'];s['budget']=clip(s['budget']+7,0,300)
    if s['governing'] and s['week']%4==0:
        pid=s['governing'][0]
        candidates=[i for i in z['institutions'].values() if i['delay']>.5]
        if candidates:propose(s,data,pid,max(candidates,key=lambda i:(i['delay'],i['id']))['id'],emit)
    for p in list(s['projects']):
        if p['stage'] in ('operating','rejected') or s['week']<p['due']:continue
        old=p['stage'];d=s['districts'][p['district']];party=s['parties'][p['party']]
        if old=='proposed':
            # Opposition needs allies; proposals can genuinely fail.
            agree=p['party'] in s['governing'] or any(sum(abs(party['ideology'][a]-s['parties'][q]['ideology'][a]) for a in data['axes'])/4<40 for q in s['governing'])
            p['stage']='approved' if agree and party['active'] else 'rejected';p['due']=s['week']+1
        elif old=='approved':
            if s['budget']<p['cost']:
                p['due']=s['week']+2
                if s['week']-p['started']>16:p['stage']='rejected'
                else:continue
            else:s['budget']-=p['cost'];p['spent']=p['cost'];p['stage']='funded';p['due']=s['week']+1
        elif old=='funded':p['stage']='building';p['due']=s['week']+1
        elif old=='building':
            pace=(15+p['quality']*.18)*(.45 if d['weather']>20 else 1)
            p['progress']=clip(p['progress']+pace)
            p['due']=s['week']+1
            if p['progress']>=100:p['stage']='staffing'
            # Low-honesty politicians may announce opening before service exists.
            if not p['public_open'] and p['progress']>=40 and s['actors'][party['leader']]['honesty']<55:
                p['public_open']=True
                e=emit(s,'opening_claim',party['name']+' объявляет об открытии проекта '+p['id']+' до готовности обслуживания',p['district'],'services',p['party'],[p['last_event']])
                p['last_event']=e['id'];document(s,'opening_claim',p,emit,True)
        elif old=='staffing':
            if p['institution']:
                i=z['institutions'][p['institution']]
                # Recruitment requires available labour and successive weeks.
                p['recruited']=clip(p['recruited']+2+d['jobs']*.05);p['due']=s['week']+1
                if p['recruited']<75:continue
                i['staff']=max(i['staff'],p['recruited']);i['capacity']+=p['gain'];i['condition']=clip(i['condition']+12)
            else:d[p['field']]=clip(d[p['field']]+p['gain'])
            p['stage']='operating';p['public_open']=True;p['completed']=s['week'];p['due']=s['week']
        e=emit(s,('policy' if p['stage']=='funded' else 'project_'+p['stage']),p['id']+' / '+STAGES[p['stage']]+' / '+d['name'],p['district'],p['topic'],p['party'],[p['last_event']] if p['last_event'] else [])
        p['last_event']=e['id']
        if p['institution'] and p['stage']=='operating':z['institutions'][p['institution']]['cause']=e['id']
        document(s,'inspection' if p['stage']=='staffing' else 'status',p,emit,p['stage'] in ('operating','rejected'))
    # Upkeep is a real budget expenditure, not an endless instant buff.
    for i in z['institutions'].values():
        upkeep=data['civic']['upkeep']
        if s['budget']>=upkeep:s['budget']-=upkeep;i['condition']=clip(i['condition']+.04)
        else:i['condition']=clip(i['condition']-.15)
    recent=[p for p in s['projects'] if p['stage'] in ('operating','rejected')][-16:]
    s['projects']=[p for p in s['projects'] if p['stage'] not in ('operating','rejected')]+recent


def investigations(s,data,rng,emit):
    z=s['civic'];journalists=[(aid,a) for aid,a in s['actors'].items() if a['alive'] and a['role']=='journalist']
    if not journalists:return
    for doc in z['documents']:
        if s['week']-doc['week']>1 and not doc['published']:doc['access']=clip(doc['access']+.02*journalists[0][1]['competence']/50,0,1)
        if doc['checked'] or doc['kind']!='opening_claim' or not doc['public_open']:continue
        evidence=next((q for q in reversed(z['documents']) if q['project']==doc['project'] and doc['week']<=q['week']<=doc['week']+2 and q['stage'] not in ('proposed','approved','funded') and q['kind']!='opening_claim' and (q['published'] or q['access']>.3)),None)
        if not evidence:continue
        if any(c['project']==doc['project'] for c in z['cases']):continue
        aid,a=journalists[0]
        if rng.random()>a['competence']/120:continue
        cid='C'+str(z['next_case']);z['next_case']+=1
        e=emit(s,'investigation_open',a['name']+' сопоставляет объявление '+doc['id']+' с актом '+evidence['id'],doc['district'],'services',doc['party'],[doc['event'],evidence['event']])
        case={'id':cid,'project':doc['project'],'party':doc['party'],'district':doc['district'],'journalist':aid,
              'documents':[doc['id'],evidence['id']],'stage':'checking','due':s['week']+2,'cause':e['id'],'witness':False,'result':''}
        z['cases'].append(case);doc['checked']=True
    for case in z['cases']:
        if case['stage']!='checking' or case['due']>s['week']:continue
        docs=[next((d for d in z['documents'] if d['id']==key),None) for key in case['documents']]
        if len(docs)!=2 or any(d is None for d in docs):case['stage']='closed';case['result']='доказательства вышли из архива';continue
        claim,act=docs
        # A real mismatch, including an exonerating outcome if the act says operating.
        mismatch=claim['public_open'] and act['stage']!='operating'
        case['stage']='published';case['result']='преждевременное объявление' if mismatch else 'противоречие не подтвердилось'
        e=emit(s,'investigation' if mismatch else 'verification',case['id']+': '+case['result']+'; документы '+', '.join(case['documents']),case['district'],'services',case['party'],[case['cause']])
        case['cause']=e['id'];e['salience']=1.3 if case['witness'] else 1.0
        for d in docs:d['published']=True;d['checked']=True
    del z['cases'][:-48]


def meetings(s,data,rng,emit):
    z=s['civic']
    for m in z['meetings']:
        if m['status']!='pending' or m['due']>s['week']:continue
        a=s['actors'][m['a']];b=s['actors'][m['b']]
        if not a['alive'] or not b['alive']:m['status']='missed';continue
        willingness=(a['relations'].get(m['b'],0)+b['relations'].get(m['a'],0))/200+.3+m['strength']/100
        if rng.random()>clip(willingness,0,.95):
            m['status']='refused';emit(s,'encounter_refused','Возможность встречи не привела к разговору: участники отказались',m['district'],causes=[m['cause']]);continue
        m['status']='met'
        # Temperament and existing relationship can lead to disagreement, not a forced treaty.
        change=6 if willingness>.5 else -6
        a['relations'][m['b']]=clip(a['relations'].get(m['b'],0)+change,-100,100);b['relations'][m['a']]=clip(b['relations'].get(m['a'],0)+change,-100,100)
        e=emit(s,'encounter',a['name']+' и '+b['name']+(' нашли общий язык' if change>0 else ' поспорили'),m['district'],causes=[m['cause']])
        if a['role']=='journalist' or b['role']=='journalist':
            for case in z['cases']:
                if case['stage']=='checking' and case['district']==m['district']:
                    e['causes'].append(case['cause']);case['witness']=True;case['cause']=e['id']
        else:
            pids=[pid for pid,p in s['parties'].items() if p['leader'] in (m['a'],m['b']) and p['active']]
            for g in z['associations']:
                if g['active'] and g['district']==m['district']:
                    for pid in pids:g['stances'][pid]=clip(g['stances'].get(pid,0)+change,-100,100)
    del z['meetings'][:-32]


def power(s,data,cmd,cause):
    z=s['civic'];key=cmd['power']
    if key=='discovery':
        doc=next((d for d in z['documents'] if d['id']==cmd.get('document_id')),None)
        if not doc:raise RuleError('Выберите существующий документ D…')
        from .world import affected
        if doc['district'] not in {c['district'] for c in affected(s,cmd.get('target','all'))}:raise RuleError('Документ относится к другому району')
        if doc['access']>=1:raise RuleError('Доступ к этому документу уже открыт')
        if doc['event']:cause['causes'].append(doc['event'])
        doc['access']=clip(doc['access']+cmd['strength']/30,0,1)
    elif key=='encounter':
        a=cmd.get('actor_a');b=cmd.get('actor_b')
        if a==b or any(x not in s['actors'] or not s['actors'][x]['alive'] for x in (a,b)):raise RuleError('Для встречи нужны два разных действующих персонажа')
        from .world import affected
        cs=affected(s,cmd.get('target','all'));did=s['actors'][a]['district'] if cmd.get('target','all')=='all' else cs[0]['district']
        z['meetings'].append({'a':a,'b':b,'district':did,'strength':cmd['strength'],'due':s['week']+1,'status':'pending','cause':cause['id']});del z['meetings'][:-32]
    elif key=='coordination':
        group=cmd.get('association_id')
        from .world import affected
        districts={c['district'] for c in affected(s,cmd.get('target','all'))}
        if not any(g['active'] and g['district'] in districts and (not group or g['id']==group) for g in z['associations']):raise RuleError('Нет действующего объединения в выбранной аудитории')


def record_changes(s,before,attract,emit_start):
    total=max(1,sum(c['population'] for c in s['cohorts']));by_party={}
    for c in s['cohorts']:
        for pid,p in s['parties'].items():
            if not p['active'] or (c['id'],pid) not in before:continue
            old,parts=before[c['id'],pid];now,new=attract(s,c,pid)
            row=by_party.setdefault(pid,{'delta':0.,'parts':{k:0. for k in parts},'causes':set()})
            row['delta']+=(now-old)*c['population']/total
            for k in parts:row['parts'][k]+=(new[k]-parts[k])*c['population']/total
            if c.get('service_cause'):row['causes'].add(c['service_cause'])
    for pid,row in by_party.items():
        if abs(row['delta'])<.01:continue
        recent=[e['id'] for e in s['events'] if e['id']>=emit_start and e['party']==pid]
        s['civic']['changes'].append({'week':s['week'],'party':pid,'delta':row['delta'],'parts':row['parts'],'causes':sorted(row['causes'])[-4:]+recent[-4:]})
    del s['civic']['changes'][:-64]


def validate(s,data,numeric):
    z=s['civic']
    expected={'institutions','associations','documents','cases','meetings','causal','changes','next_project','next_document','next_association','next_case'}
    if not isinstance(z,dict) or set(z)!=expected:raise DataError('god save: civic schema')
    for k in ('next_project','next_document','next_association','next_case'):
        if type(z[k]) is not int or z[k]<1:raise DataError('god save: civic counter')
    if set(z['institutions'])!={d+':'+k for d in s['districts'] for k in KINDS}:raise DataError('god save: institutions')
    for iid,i in z['institutions'].items():
        if i['id']!=iid or i['district'] not in s['districts'] or i['kind'] not in KINDS:raise DataError('god save: institution reference')
        for k in ('capacity','demand','served','queue'):numeric(i[k],0,1e8,'institution '+k)
        for k in ('staff','condition'):numeric(i[k],0,100,'institution '+k)
        numeric(i['delay'],0,20,'delay')
        if i['served']>i['demand']+1e-6 or not math.isclose(i['queue'],i['demand']-i['served'],abs_tol=1e-5):raise DataError('god save: service conservation')
    if len(z['associations'])>36 or len(z['documents'])>192 or len(z['cases'])>48 or len(z['meetings'])>32 or len(z['causal'])>900 or len(z['changes'])>64:raise DataError('god save: civic limits')
    cohort_ids={c['id']:c['population'] for c in s['cohorts']}
    gids=set()
    for g in z['associations']:
        if g['id'] in gids or g['institution'] not in z['institutions'] or g['district'] not in s['districts'] or type(g['active']) is not bool:raise DataError('god save: association')
        gids.add(g['id'])
        if g['active'] and (g['leader'] not in g['members'] or not g['members']):raise DataError('god save: association leader')
        for cid,n in g['members'].items():
            if cid not in cohort_ids or type(n) is not int or not 0<=n<=(cohort_ids[cid] if g['active'] else 1_000_000):raise DataError('god save: association residents')
        for k in ('resources','fatigue'):numeric(g[k],0,100,'association '+k)
        numeric(g['demand'],0,20,'association demand')
        for pid,v in g['stances'].items():
            if pid not in s['parties']:raise DataError('god save: association party')
            numeric(v,-100,100,'association stance')
    docs=set()
    for d in z['documents']:
        if d['id'] in docs or d['party'] not in s['parties'] or d['district'] not in s['districts'] or d['stage'] not in STAGES or type(d['published']) is not bool or type(d['public_open']) is not bool or type(d['checked']) is not bool:raise DataError('god save: document')
        if not isinstance(d['id'],str) or not d['id'].startswith('D') or type(d['week']) is not int or d['week']<1 or type(d['event']) is not int or d['event']<0 or not isinstance(d['project'],str):raise DataError('god save: document identity')
        numeric(d['cost'],0,300,'document cost')
        docs.add(d['id']);numeric(d['access'],0,1,'document access');numeric(d['spent'],0,300,'spent');numeric(d['progress'],0,100,'document progress')
    project_ids=set()
    for p in s['projects']:
        if not isinstance(p['id'],str) or p['id'] in project_ids or type(p['public_open']) is not bool:raise DataError('god save: project identity')
        project_ids.add(p['id']);numeric(p['recruited'],0,100,'project staff')
        if p['stage'] not in STAGES or (p['institution'] and p['institution'] not in z['institutions']) or type(p['due']) is not int or p['due']<1:raise DataError('god save: project stages')
        for k in ('cost','spent'):numeric(p[k],0,300,'project money')
        numeric(p['progress'],0,100,'project progress')
    for m in z['meetings']:
        if m['a'] not in s['actors'] or m['b'] not in s['actors'] or m['a']==m['b'] or m['status'] not in ('pending','missed','refused','met') or type(m['due']) is not int:raise DataError('god save: meeting')
        numeric(m['strength'],0,30,'meeting opportunity')
    for c in s['cohorts']:numeric(c['service_pressure'],0,20,'service pressure')
    case_ids=set()
    for case in z['cases']:
        if case['id'] in case_ids or case['party'] not in s['parties'] or case['journalist'] not in s['actors'] or case['district'] not in s['districts'] or case['stage'] not in ('checking','closed','published') or type(case['due']) is not int or case['due']<1 or type(case['witness']) is not bool or not isinstance(case['result'],str) or len(case['documents'])!=2:raise DataError('god save: investigation case')
        if len(set(case['documents']))!=2 or any(not isinstance(v,str) or not v.startswith('D') for v in case['documents']):raise DataError('god save: case evidence')
        case_ids.add(case['id'])
    for key in ('causal','documents','changes'):
        if not isinstance(z[key],list):raise DataError('god save: civic list')
    for node in z['causal']:
        if type(node['id']) is not int or node['id']<1 or type(node['week']) is not int or node['week']<1 or not isinstance(node['text'],str) or len(node['text'])>240 or not isinstance(node['causes'],list) or any(type(v) is not int or v<0 for v in node['causes']):raise DataError('god save: causal record')
    for c in z['changes']:
        if c['party'] not in s['parties']:raise DataError('god save: change party')
        numeric(c['delta'],-100,100,'change')
        for v in c['parts'].values():numeric(v,-200,200,'component change')


def member_attraction(s,c,pid):
    value=0.0
    for g in s.get('civic',{}).get('associations',[]):
        if not g['active'] or not g['members'].get(c['id']):continue
        pos=g['positions'].get(pid)
        if not pos:continue
        stance=g['stances'].get(pid,0) if pos['event'] in c['known'] else pos['previous']['stance'] if pos['previous']['event'] in c['known'] else 0
        value+=stance*.025*g['members'][c['id']]/max(1,c['population'])
    return clip(value,-5,5)
