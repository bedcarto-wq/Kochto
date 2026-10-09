"""Representative household accounts and bounded life choices per cohort.
No fabricated individual families. Amounts are model roubles per week/home.
Accounts are conserved; shortages, loans and decisions have material effects.
"""
from __future__ import annotations
import math
from ..engine import DataError

ACTIONS={'reserve':'Создать резерв','work':'Подработать','study':'Получить квалификацию','care':'Заботиться о близких','community':'Помочь соседям'}
FIELDS={'savings','debt','income','needs','paid','shortage','security','skill','training','free_time','fatigue','balance','last_event','ledger','history'}
LEDGER={'opening_savings','opening_debt','income','interest','needs','paid','withdrawal','loan','repayment','deposit','closing_savings','closing_debt'}

def clip(v,a=0,b=100):return max(a,min(b,v))

def initialize(c,week=1):
    if 'household' in c:return
    c['household']={'savings':max(0,c['income']*100*(.5 if 'lower' in c['tags'] else 2)),
        'debt':c['income']*60 if 'lower' in c['tags'] else 0.0,'income':0.0,'needs':0.0,'paid':0.0,
        'shortage':0.0,'security':50.0,'skill':0.0,'training':0,'free_time':40.0,'fatigue':0.0,
        'balance':0.0,'last_event':0,'ledger':{},'history':[]}
    c['life']={'action':'reserve','started':week,'remaining':0,'completed':0,'review':0,'options':[]}

def expenses(c,d,cfg):
    family='parent' in c['tags'];elder='elder' in c['tags']
    size=cfg['family_cost'] if family else 1.0
    return {'food':cfg['food']*size,'housing':(cfg['housing']+d['income']*cfg['housing_income'])*size,
        'transport':cfg['transport']*(1+(100-d['access'])/100)*(0.6 if elder else 1),
        'health':cfg['health']*(1+(100-d['health'])/60)*(1.5 if elder else 1),
        'dependents':cfg['dependents'] if family else 0.0,
        'study':cfg['study_fee'] if c['life']['action']=='study' else 0.0}

def earnings(c,d,cfg):
    h=c['household'];elder='elder' in c['tags']
    base=cfg['base_income']+c['income']*cfg['income_factor']
    base*=cfg['family_earners'] if 'parent' in c['tags'] else 1
    base*=(cfg['pension_factor'] if elder else .65+d['jobs']/200)
    base*=1+h['skill']/200
    extra=cfg['side_income']*(.4+d['jobs']/150) if c['life']['action']=='work' and not elder else 0
    return base+extra

def decide(c,d,cfg,week):
    h=c['household'];life=c['life']
    if life['action']=='study' and life['remaining']>0 and h['security']>15:return
    rows=[]
    urgency=100-h['security'];family='parent' in c['tags'];elder='elder' in c['tags']
    def add(action,score,reason):rows.append({'action':action,'score':round(score,3),'reason':reason})
    add('reserve',35+min(12,h['debt']/max(1,h['income'],earnings(c,d,cfg)))*3, 'Погашение долга и запас на обязательные расходы')
    if not elder and d['jobs']>20:
        add('work',urgency*.85+(20 if h['shortage']>0 else 0)-h['fatigue']*.55,'Недостаток средств; цена — усталость и меньше свободного времени')
    if not elder and h['savings']>cfg['study_fee']*8 and h['security']>35 and h['skill']<40:
        add('study',40+(100-d['jobs'])*.20-h['skill']*.7,'Курс на восемь недель: расходы сейчас, доход после завершения')
    if family or elder:
        add('care',25+(100-d['health'])*.55+h['fatigue']*.35,'Нужды близких, здоровье и восстановление')
    add('community',20+c['engagement']*.35+d['solidarity']*.15-h['fatigue']*.25,'Коллективная помощь вместо дополнительного заработка')
    chosen=max(rows,key=lambda x:(x['score'],x['action']))
    changed=life['action']!=chosen['action'];life.update({'action':chosen['action'],'review':week,'options':rows})
    if changed:
        life['started']=week;life['remaining']=8 if chosen['action']=='study' else 4
    c['goal']=ACTIONS[life['action']]

def settle(h,income,needs,cfg):
    """Money identity: Δ(savings-debt) == income-paid-interest."""
    savings=h['savings'];debt=h['debt'];interest=debt*cfg['interest']
    debt+=interest;cash=income
    withdrawal=min(savings,max(0,needs-cash));savings-=withdrawal;cash+=withdrawal
    loan=min(max(0,needs-cash),max(0,income*cfg['credit_weeks']-debt));debt+=loan;cash+=loan
    paid=min(needs,cash);cash-=paid
    repayment=min(debt,cash*(.85 if h.get('reserve',False) else .55));debt-=repayment;cash-=repayment
    deposit=cash;savings+=deposit
    ledger={'opening_savings':h['savings'],'opening_debt':h['debt'],'income':income,'interest':interest,'needs':needs,'paid':paid,
        'withdrawal':withdrawal,'loan':loan,'repayment':repayment,'deposit':deposit,'closing_savings':savings,'closing_debt':debt}
    h.update({'savings':savings,'debt':debt,'income':income,'needs':needs,'paid':paid,'shortage':needs-paid,'balance':income-paid-interest,'ledger':ledger})
    return ledger

def tick(s,data,rng,emit):
    cfg=data['living'];completed={}
    for c in s['cohorts']:
        if not c['population']:continue
        h=c['household'];d=s['districts'][c['district']];life=c['life'];old_security=h['security']
        if 'elder' in c['tags'] and life['action'] in ('work','study'):
            life['action']='reserve';life['remaining']=0;c['goal']=ACTIONS['reserve']
        if s['week']==1 or s['week']%4==0:decide(c,d,cfg,s['week'])
        costs=expenses(c,d,cfg);income=earnings(c,d,cfg)
        # A reserve decision directs more free cash to repayment, never invents money.
        reserve=life['action']=='reserve';h['reserve']=reserve
        settle(h,income,sum(costs.values()),cfg);del h['reserve']
        h['security']=clip(55+min(30,h['savings']/max(1,h['needs'])*10)-h['debt']/max(1,income)*7-h['shortage']/max(1,h['needs'])*80)
        action=life['action'];h['fatigue']=clip(h['fatigue']+(6 if action=='work' else -4 if action=='care' else -2))
        h['free_time']=clip(45-(18 if action=='work' else 12 if action=='study' else 8 if action in ('care','community') else 0)-h['fatigue']*.2)
        if action=='study' and h['shortage']==0:
            h['training']+=1;life['remaining']=max(0,8-h['training'])
            if h['training']>=8:
                h['skill']=clip(h['skill']+5,0,40);h['training']=0;life['completed']+=1;life['remaining']=0;life['action']='reserve'
                completed.setdefault(c['district'],[]).append(c)
                c['goal']=ACTIONS['reserve']
        elif action=='care':c['stress']=clip(c['stress']-1.5)
        elif action=='community':
            local=max(1,d['population']);d['solidarity']=clip(d['solidarity']+c['population']/local*.8)
            c['engagement']=clip(c['engagement']+.25)
        if action!='study':life['remaining']=max(0,life['remaining']-1)
        hardship=100-h['security']+h['fatigue']*.2
        c['stress']=clip(c['stress']+.10*(hardship-c['stress']))
        c['attention']['jobs']=clip(c['attention']['jobs']+max(0,60-h['security'])*.04)
        c['engagement']=clip(c['engagement']+(h['free_time']-30)*.008)
        # Personal material experience affects incumbent trust, not divine support bonuses.
        for pid in s['governing']:
            change=clip((h['security']-old_security)*.05-h['shortage']/max(1,h['needs'])*.3,-.4,.3)/max(1,len(s['governing']))
            c['trust'][pid]=clip(c['trust'][pid]+change)
        h['history'].append({'week':s['week'],'balance':round(h['balance'],2),'security':round(h['security'],2),'action':action})
        del h['history'][:-16]
    for did,cs in completed.items():
        e=emit(s,'education',str(len(cs))+' когорт в '+s['districts'][did]['name']+' завершили курс; квалификация повышает будущий доход',did,'jobs')
        for c in cs:c['household']['last_event']=e['id']
    if s['week']%8==0:
        for did,d in s['districts'].items():
            cs=[c for c in s['cohorts'] if c['district']==did and c['population']]
            stressed=sum(c['population'] for c in cs if c['household']['security']<30)
            if stressed:
                emit(s,'household','В '+d['name']+' материальная неустойчивость затрагивает '+str(stressed)+' избирателей: долги, расходы и нехватка резерва',did,'jobs')

def validate(c,numeric):
    h=c['household'];life=c['life']
    if not isinstance(h,dict) or set(h)!=FIELDS:raise DataError('god save: household fields')
    for key in ('savings','debt','income','needs','paid','shortage'):numeric(h[key],0,1e12,'household '+key)
    for key in ('security','skill','free_time','fatigue'):numeric(h[key],0,40 if key=='skill' else 100,'household '+key)
    numeric(h['balance'],-1e12,1e12,'household balance')
    for key in ('training','last_event'):
        if type(h[key]) is not int or h[key]<0 or (key=='training' and h[key]>7):raise DataError('god save: household counter')
    if not isinstance(h['ledger'],dict) or h['ledger'] and set(h['ledger'])!=LEDGER:raise DataError('god save: ledger fields')
    if h['paid']>h['needs']+1e-7 or not math.isclose(h['shortage'],h['needs']-h['paid'],abs_tol=1e-6):raise DataError('god save: household consumption')
    if h['ledger']:
        l=h['ledger']
        for v in l.values():numeric(v,0,1e12,'ledger amount')
        if not math.isclose(l['closing_savings']-l['opening_savings']-l['closing_debt']+l['opening_debt'],l['income']-l['paid']-l['interest'],abs_tol=1e-5):raise DataError('god save: unbalanced household ledger')
        checks=[(l['closing_savings'],l['opening_savings']-l['withdrawal']+l['deposit']),(l['closing_debt'],l['opening_debt']+l['interest']+l['loan']-l['repayment']),(l['income']+l['withdrawal']+l['loan'],l['paid']+l['repayment']+l['deposit'])]
        if any(not math.isclose(a,b,abs_tol=1e-5) for a,b in checks):raise DataError('god save: inconsistent household transactions')
        if l['closing_savings']!=h['savings'] or l['closing_debt']!=h['debt']:raise DataError('god save: ledger and balance disagree')
    if not isinstance(h['history'],list) or len(h['history'])>16:raise DataError('god save: household history')
    for row in h['history']:
        if set(row)!={'week','balance','security','action'} or type(row['week']) is not int or row['week']<1 or row['action'] not in ACTIONS:raise DataError('god save: household history row')
        numeric(row['balance'],-1e12,1e12,'history balance');numeric(row['security'],0,100,'history security')
    if not isinstance(life,dict) or set(life)!={'action','started','remaining','completed','review','options'} or life['action'] not in ACTIONS:raise DataError('god save: life plan')
    for key in ('started','remaining','completed','review'):
        if type(life[key]) is not int or life[key]<0 or (key=='remaining' and life[key]>8):raise DataError('god save: life counter')
    if not isinstance(life['options'],list) or len(life['options'])>5:raise DataError('god save: life alternatives')
    for row in life['options']:
        if set(row)!={'action','score','reason'} or row['action'] not in ACTIONS or not isinstance(row['reason'],str):raise DataError('god save: life alternative')
        numeric(row['score'],-1e12,1e12,'life score')


def transfer_mean(origin,dest,count):
    """Financial stocks travel with migrants, preserving cohort-weighted totals.
    Histories/life decisions remain cohort-level, not personal biographies.
    """
    total=dest['population']+count
    for key in ('savings','debt','skill','fatigue','free_time'):
        dest['household'][key]=(dest['household'][key]*dest['population']+origin['household'][key]*count)/max(1,total)
    dest['household']['ledger']={}
