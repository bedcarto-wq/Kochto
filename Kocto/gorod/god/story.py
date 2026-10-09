"""One finite scenario on the real aggregate city. No scripted election winner.
Named residents are narrative representatives of existing cohorts, not new people.
"""
from __future__ import annotations
import copy
from ..engine import DataError,RuleError

GOALS={'livelihood':'Помочь семьям пережить перемены','health':'Сохранить здоровье и возможность заработка','ties':'Не разрушить соседские связи'}

def validate_rules(r):
    if set(r)!={'decision_weeks','end_week','initial_capital','initial_pollution','conversion_cost','conversion_steps'} or r['decision_weeks']!=[8,16] or r['end_week']!=26 or r['conversion_steps']!=6:raise DataError('scenario: calendar')
    for k in ('initial_capital','initial_pollution','conversion_cost'):
        if type(r[k]) not in (int,float) or not 0<r[k]<=100:raise DataError('scenario: '+k)

def start(s,data,emit,goal='livelihood'):
    if goal not in GOALS:raise RuleError('Неизвестное обязательство')
    if s['week']!=1 or s['revision']!=0:raise RuleError('Сценарий начинается только в новом мире')
    d=s['districts']['factory'];f=s['firms']['factory'];r=data['scenario_rules'];f['capital']=r['initial_capital'];d['pollution']=r['initial_pollution']
    residents=[]
    for name,tags,wish in [('Ирина','worker','Сохранить заработок и время для семьи'),('Михаил','student','Получить профессию, не уезжая из района'),('Вера','elder','Сохранить здоровье и помощь соседей'),('Денис','business','Сохранить дело, от которого зависят другие')]:
        c=next(c for c in s['cohorts'] if c['district']=='factory' and tags in c['tags'])
        residents.append({'name':name,'cohort':c['id'],'wish':wish,'status':'Надежда ещё не проверена','last':'','changes':[]})
    st={'id':'last_winter','goal':goal,'started':1,'end':r['end_week'],'finished':False,'continued':False,'plant':'uncertain','progress':0,'decisions':[],
        'residents':residents,'baseline':{'jobs':d['jobs'],'health':d['health'],'solidarity':d['solidarity'],'pollution':d['pollution'],'workers':f['workers']},
        'weekly':[],'epilogue':[],'history':[],'cost':0.0,'last_event':0}
    s['story']=st
    e=emit(s,'story_origin','Последняя зима комбината: собственник пересмотрит работу на неделе 8; новые власти получат второй шанс на неделе 16. Итоги — после недели 26.','factory','jobs');st['last_event']=e['id']
    return st

def before(s,data,emit):
    st=s['story']
    if not st or st['finished']:return
    d=s['districts']['factory'];f=s['firms']['factory'];r=data['scenario_rules'];week=s['week']
    if st['plant'] not in ('closed','converting','converted'):
        f['capital']=max(0,f['capital']-1.2);d['pollution']=min(100,d['pollution']+.25);d['health']=max(0,d['health']-.12)
    elif st['plant']=='closed':
        d['pollution']=max(0,d['pollution']-.6)
        # Owner can rebuild capital from the district economy, not from phantom production.
        f['capital']=min(100,f['capital']+max(0,d['income']-45)*.2)
    if week in r['decision_weeks']:
        leaders=[s['actors'][s['parties'][pid]['leader']] for pid in s['governing']]
        capable=any(a['alive'] and a['competence']>=45 for a in leaders)
        if st['plant']!='converted' and st['plant']!='converting':
            if f['capital']>=25 and d['infra']>=60 and d['access']>=65 and capable and s['budget']>=r['conversion_cost']:
                s['budget']-=r['conversion_cost'];st['cost']+=r['conversion_cost'];st['plant']='converting';f['status']='переоборудование'
                text='Власть и собственник начали переоборудование: есть средства, транспорт и подготовленное управление. Бюджет: −'+str(r['conversion_cost'])
            elif f['capital']>=30:
                st['plant']='working';f['status']='работает';text='Собственник продолжает прежнее производство: средств пока хватает, экологическая проблема остаётся'
            else:
                removed=f['workers'];f['workers']=0;f['status']='закрыто';d['jobs']=max(0,d['jobs']-min(20,removed/50));st['plant']='closed';text='Собственник закрыл производство: капитал исчерпан, условия переоборудования не сложились. Потеря рабочих мест: '+str(removed)
            e=emit(s,'story_decision',text,'factory','jobs',causes=[st['last_event']]);st['last_event']=e['id'];st['decisions'].append({'week':week,'result':st['plant'],'event':e['id']})
    if st['plant']=='converting':
        # Real successive work, vulnerable to weather and unavailable transport.
        if d['weather']<=20 and d['access']>=50:st['progress']+=1
        if st['progress']>=r['conversion_steps']:
            st['plant']='converted';f['status']='переоборудовано';f['workers']=max(650,int(st['baseline']['workers']*.85));f['wage']=48;d['jobs']=min(100,d['jobs']+6);d['pollution']=max(0,d['pollution']-22)
            e=emit(s,'story_operation','Переоборудование завершено: загрязнение снизилось, рабочие места сохранены не полностью.','factory','ecology',causes=[st['last_event']]);st['last_event']=e['id']

def resident_status(s,r):
    c=next(c for c in s['cohorts'] if c['id']==r['cohort']);h=c['household'];d=s['districts'][c['district']];life=c['life']
    if not c['population']:return 'Исходная когорта больше не представлена в районе'
    if 'student' in c['tags']:
        if h['skill']>0:return 'Обучение принесло квалификацию; новое будущее стало доступнее'
        if life['action']=='study':return 'Учится: нужны оплаченные недели и свободное время'
        return 'Профессиональный путь ещё не определился'
    if 'elder' in c['tags']:
        return 'Здоровье и доступ к помощи остаются уязвимыми' if d['health']<65 or c['service_pressure']>5 else 'Условия здоровья и помощи стали приемлемее'
    if h['shortage']>0:return 'Нужды не покрыты: семья вынуждена искать выход'
    if h['debt']>h['savings']:return 'Нужды оплачены, но долг превышает резерв'
    if life['action']=='community':return 'Отдаёт время помощи соседям'
    return 'Есть материальный запас, но будущий заработок не гарантирован'

def after(s,data,emit,start_event):
    st=s['story']
    if not st or st['finished']:return False
    week=s['week'];changed=[]
    for r in st['residents']:
        status=resident_status(s,r);r['status']=status
        if status!=r['last']:
            r['changes'].append({'week':week,'text':status});del r['changes'][:-12];changed.append(r['name']+': '+status);r['last']=status
    upcoming=next((w for w in data['scenario_rules']['decision_weeks'] if w>week),None) if st['plant']!='converted' else None
    deadline='До решения о комбинате: '+str(upcoming-week)+' нед.' if upcoming else 'До эпилога: '+str(max(0,st['end']-week))+' нед.'
    actual=[e['text'] for e in s['events'] if e['id']>=start_event and e['kind'] in ('story_decision','story_operation','election','crisis','investigation','civic_success')]
    st['weekly']=[deadline,'Для людей: '+(' / '.join(changed[:2]) if changed else 'Резких перемен в отмеченных судьбах нет; жизненные решения продолжаются.'),'Поворот недели: '+(actual[-1] if actual else 'Город продолжает жить без крупного поворота.')]
    if week>=st['end']:
        st['finished']=True;st['epilogue']=epilogue(s);emit(s,'story_epilogue','История «Последняя зима комбината» завершена. Мир можно продолжить без нового обязательного финала.','factory');return True
    return False

def epilogue(s):
    st=s['story'];d=s['districts']['factory'];f=s['firms']['factory'];b=st['baseline']
    lines=['ПОСЛЕДНЯЯ ЗИМА КОМБИНАТА — ИТОГИ','Ваше обязательство: '+GOALS[st['goal']], 'Комбинат: '+f['status']+'; работников '+str(f['workers'])+' (в начале '+str(b['workers'])+').',
        'Цена и последствия: бюджет переоборудования '+str(st['cost'])+'; загрязнение '+str(round(b['pollution']))+' → '+str(round(d['pollution']))+'; занятость '+str(round(b['jobs']))+' → '+str(round(d['jobs']))+'.',
        'Здоровье: '+str(round(b['health']))+' → '+str(round(d['health']))+'; соседские связи: '+str(round(b['solidarity']))+' → '+str(round(d['solidarity']))+'.']
    if st['goal']=='livelihood':lines.append('Обязательство: материальная устойчивость семей остаётся проблемой.' if any(next(c for c in s['cohorts'] if c['id']==r['cohort'])['household']['debt']>next(c for c in s['cohorts'] if c['id']==r['cohort'])['household']['savings'] for r in st['residents']) else 'Обязательство: у отмеченных когорт есть резерв; это не гарантия благополучия всех семей.')
    elif st['goal']=='health':lines.append('Обязательство: '+('условия здоровья улучшились без полного исчезновения производства.' if d['health']>=b['health'] and f['workers']>0 else 'здоровье и заработок не удалось улучшить одновременно.'))
    else:lines.append('Обязательство: '+('соседские связи укрепились.' if d['solidarity']>=b['solidarity'] else 'соседские связи ослабли.'))
    for r in st['residents']:lines.append(r['name']+' хотел(а): '+r['wish']+'. Итог: '+r['status']+'.')
    elections=s['elections'];lines.append('Выборы произошли по общей модели; победитель сценарием не назначался. Правительство: '+', '.join(s['parties'][p]['name'] for p in s['governing']))
    miracles=[e for e in s['events'] if e['kind']=='miracle'];lines.append('Пересмотров обязательства: '+str(len(st['history']))+'. Ваши вмешательства: '+str(len(miracles))+'. Решения людей: '+str(len(st['decisions']))+' пересмотра судьбы комбината; партии и домохозяйства действовали самостоятельно.')
    if s['editor_used']:lines.append('Использован прямой редактор: исход нельзя считать результатом только непрямого влияния.')
    lines+=['Изменения — факты симуляции, не точное доказательство вклада каждого чуда. Контрфактический исход не рассчитывается.','Неопределённость остаётся: люди представлены когортами; личные истории — их повествовательные представители, не отдельные семьи.']
    return [line for line in lines if line]

def choose(s,goal,emit):
    st=s['story']
    if not st or st['finished'] or goal not in GOALS:raise RuleError('Обязательство недоступно')
    if goal==st['goal']:return
    st['history'].append({'week':s['week'],'old':st['goal'],'new':goal});del st['history'][:-24];st['goal']=goal
    emit(s,'story_commitment','Игрок пересмотрел обязательство: '+GOALS[goal]);s['revision']+=1

def validate(s,data):
    st=s['story']
    if st is None:return
    keys={'id','goal','started','end','finished','continued','plant','progress','decisions','residents','baseline','weekly','epilogue','history','cost','last_event'}
    if not isinstance(st,dict) or set(st)!=keys or st['id']!='last_winter' or st['goal'] not in GOALS or st['end']!=26 or st['started']!=1 or st['plant'] not in ('uncertain','working','closed','converting','converted'):raise DataError('scenario: state')
    if type(st['finished']) is not bool or type(st['continued']) is not bool or type(st['progress']) is not int or not 0<=st['progress']<=6 or type(st['cost']) not in (int,float) or not 0<=st['cost']<=64:raise DataError('scenario: progress')
    if len(st['residents'])!=4 or len(st['decisions'])>2 or len(st['history'])>24 or len(st['weekly'])>3 or len(st['epilogue'])>30:raise DataError('scenario: bounds')
    if st['continued'] and not st['finished']:raise DataError('scenario: continuation')
    if st['finished'] and s['week']<27:raise DataError('scenario: premature epilogue')
    if set(st['baseline'])!={'jobs','health','solidarity','pollution','workers'} or any(type(v) not in (int,float) or v<0 for v in st['baseline'].values()):raise DataError('scenario: baseline')
    weeks=set()
    for d in st['decisions']:
        if set(d)!={'week','result','event'} or d['week'] not in (8,16) or d['week'] in weeks or d['result'] not in ('working','closed','converting') or type(d['event']) is not int or d['event']<1:raise DataError('scenario: decision')
        weeks.add(d['week'])
    for h in st['history']:
        if set(h)!={'week','old','new'} or type(h['week']) is not int or not 1<=h['week']<=26 or h['old'] not in GOALS or h['new'] not in GOALS:raise DataError('scenario: commitment')
    ids={c['id'] for c in s['cohorts']}
    for r in st['residents']:
        if set(r)!={'name','cohort','wish','status','last','changes'} or r['cohort'] not in ids or len(r['changes'])>12 or any(not isinstance(r[k],str) for k in ('name','wish','status','last')):raise DataError('scenario: resident')
    if st['finished'] and not st['epilogue']:raise DataError('scenario: missing epilogue')
    for texts in (st['weekly'],st['epilogue']):
        if any(not isinstance(t,str) or len(t)>2000 for t in texts):raise DataError('scenario: text')

def briefing(s):
    st=s['story']
    if not st:return ['СВОБОДНЫЙ МИР','Город живёт без обязательного сценария. Для истории с целью начните новый мир и выберите «Последняя зима комбината».']
    d=s['districts']['factory'];f=s['firms']['factory']
    lines=['ПОСЛЕДНЯЯ ЗИМА КОМБИНАТА','Производство кормит район и загрязняет его. На неделе 8 собственник решит его судьбу; после выборов на неделе 16 появится второй шанс. Итоги — после недели 26.',
        'ВАШЕ ОБЯЗАТЕЛЬСТВО: '+GOALS[st['goal']], 'Не назначайте победителя. Помогите людям найти выход, изменяя условия. Работа, здоровье и соседские связи могут требовать разных решений.','']
    lines+=st['weekly'] or ['Пока никто не знает, каким будет исход. Наблюдение тоже допустимо: проблемы не остановятся без вас.']
    lines+=['ЛЮДИ, КОТОРЫМ ЕСТЬ ЧТО ТЕРЯТЬ']
    for r in st['residents']:lines.append(r['name']+' · '+r['wish']+'\n'+r['status']+' (когорта '+r['cohort']+').')
    lines+=['','ЧТО МЕШАЕТ ПЕРЕОБОРУДОВАНИЮ', 'Капитал предприятия '+str(round(f['capital']))+'/25; инфраструктура '+str(round(d['infra']))+'/60; доступность '+str(round(d['access']))+'/65; бюджет '+str(round(s['budget']))+'/32.',
        'Также нужен действующий руководитель власти с компетентностью не ниже 45. Решение принимают люди; погода и доступность влияют на выполнение. Показатели — условия модели, не гарантированный совет нажать кнопку.']
    lines+=['','МЕСТА','Клуб комбината: '+('работа предприятия позволяет сохранять место встреч' if f['workers'] else 'закрытие предприятия лишило район привычного места встреч')+'. Это представление состояния предприятия, не отдельный бюджет здания.',
        'Набережная: загрязнение '+str(round(d['pollution']))+'/100; здоровье района '+str(round(d['health']))+'/100. Это состояние района, не новая независимая шкала.',
        '', 'Люди здесь — повествовательные представители существующих когорт. Их статусы выводятся из бюджета, жизненного решения и услуг; отдельные биографии семей не симулируются.']
    if st['finished']:return st['epilogue']+['','Эпилог зафиксирован на завершении. «Продолжить мир» оставляет его в истории и снимает остановку времени.']
    return [line for line in lines if line]
