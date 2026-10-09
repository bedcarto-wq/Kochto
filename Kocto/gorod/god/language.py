"""Conservative free-form god interventions + composed data effects.
Neural proposals never fabricate an unimplemented mechanism or bypass guards.
"""
from __future__ import annotations
from dataclasses import dataclass,field,asdict
import re
from ..engine import RuleError, DataError, DATA_DIR, load_json
from .. import neural,nlu
from .world import affected,apply_power
from . import civic
import copy

@dataclass
class Plan:
    text:str
    commands:list=field(default_factory=list)
    blocked:list=field(default_factory=list)
    notes:list=field(default_factory=list)
    cost:int=0
    candidates:list=field(default_factory=list)
    @property
    def ready(self):return bool(self.commands) and not self.blocked
    def record(self):return asdict(self)

_CACHE={}

def model():
    if not _CACHE:
        corpus=load_json(DATA_DIR/'god_phrases.json');record=load_json(DATA_DIR/'god_neural.json')
        _CACHE['model']=neural.load(record,corpus,record['labels'])
    return _CACHE['model']


def hit(text,alias):
    return bool(re.search(r'(?<![а-яa-z])'+re.escape(alias),text))


def parse(world,text):
    plan=Plan(text if isinstance(text,str) else '')
    if not isinstance(text,str) or not text.strip():plan.blocked.append('Пустое вмешательство');return plan
    if len(text)>2000:plan.blocked.append('Максимум 2000 символов');return plan
    pieces=[p.strip(' ,') for p in re.split(r';|\bзатем\b|\bпотом\b',text,flags=re.I) if p.strip(' ,')]
    if len(pieces)>3:plan.blocked.append('Не более трёх частей за одно вмешательство');return plan
    for index,piece in enumerate(pieces,1):
        low=piece.lower().replace('ё','е');reasons=[]
        if '?' in low or re.search(r'\b(?:если|когда|иначе|либо|кроме|однако|но)\b',low):reasons.append('Условия и альтернативы требуют механики отложенных событий; они пока не исполняются автоматически')
        if re.search(r'\bне\s+(?:буду|хочу|делать|созда|увелич|сниз|усил|раскры|посыл|измен|выз|исцел|освобод|облегч|най|свест|устро)[а-я]*',low):reasons.append('Это отрицание действия')
        if any(x in low for x in ('распустить парти','популярност','процент голос','заставить голос','победить на выбор','добавить 20%')):reasons.append('Назначение политического результата — только через меню прямого управления')
        if re.search(r'[«»"“”]|\b(?:сказал|сказала|вчера|позавчера|он хочет|она хочет|он|она|они|партия|люди)\b',low):reasons.append('Цитата или прошлое событие не считаются командой')
        powers=[(sum(hit(low,a) for a in spec['aliases']),key) for key,spec in world.data['powers'].items()]
        specialized=[(n,k) for n,k in powers if n and k in civic.NEW_POWERS]
        ranked=sorted(specialized if specialized else powers,reverse=True)
        scores=model().predict(nlu.tokens(piece))
        if scores:plan.candidates.append({'part':index,'source':'локальная MLP','scores':[{ 'power':k,'score':round(v,4)} for k,v in sorted(scores.items(),key=lambda x:(-x[1],x[0]))[:3]]})
        if not ranked[0][0]:
            reasons.append('Не найден поддерживаемый механизм. Нейросеть показывает варианты, но не придумывает эффект')
            power=None
        elif len([x for x in ranked if x[0]==ranked[0][0]])>1:
            reasons.append('Несколько механизмов: разделите «затем» или выберите силу в конструкторе');power=None
        else:power=ranked[0][1]
        districts=[d for d,v in world.data['districts'].items() if any(hit(low,a) for a in v['aliases'])]
        tags=[t for t,aliases in world.data['aliases'].items() if any(hit(low,a) for a in aliases)]
        if len(districts)>1:reasons.append('Несколько районов: разделите вмешательства или выберите аудиторию')
        target=districts[0] if len(districts)==1 else 'all'
        if tags:target=('' if target=='all' else target+'&')+'|'.join(tags) if len(tags)==1 else '|'.join((('' if target=='all' else target+'&')+t) for t in tags)
        if target!='all' and not affected(world.state,target):reasons.append('Нет жителей с таким сочетанием признаков')
        topics=[t for t,v in world.data['topics'].items() if any(hit(low,a) for a in v['aliases'])]
        if len(topics)>1 and power in ('attention','information'):reasons.append('Несколько политических тем: уточните одну')
        topic=topics[0] if len(topics)==1 else ''
        if power in ('attention','information') and not topic:reasons.append('Укажите тему: работа, ЖКХ, экология, права или традиции')
        strength=15
        strength_text=re.sub(r'(?:на|срок)\s+\d+\s+нед[а-я]*','',low)
        m=re.search(r'(?:сил[аоый]*|на)\s+(-?\d+(?:[.,]\d+)?)',strength_text)
        if m:strength=float(m.group(1).replace(',','.'))
        if re.search(r'\b(?:сниз|замедл|ухудш|уменьш|болезн|бедност)[а-я]*',low):strength=-abs(strength)
        duration=4;m=re.search(r'(?:на|срок)\s+(\d+)\s+нед',low)
        if m:duration=int(m.group(1))
        if not -30<=strength<=30 or strength==0:reasons.append('Сила от −30 до 30, кроме нуля')
        if not 1<=duration<=12:reasons.append('Срок от 1 до 12 недель')
        event_id=None
        if power=='reveal':
            m=re.search(r'(?:событи[ея]|факт|#)\s*(\d+)',low)
            if m:event_id=int(m.group(1))
            else:reasons.append('Раскрытие только существующего факта: укажите «событие N» из хроники')
        if reasons:plan.blocked.extend('Часть '+str(index)+': '+r for r in reasons)
        if power:
            cmd={'power':power,'target':target,'topic':topic,'strength':strength,'duration':duration}
            if event_id is not None:cmd['event_id']=event_id
            if power=='discovery':
                match=re.search(r'\b(?:документ[а-я]*\s*)?d(\d+)\b',low)
                if match:cmd['document_id']='D'+match.group(1)
                else:plan.blocked.append('Часть '+str(index)+': укажите существующий документ D…')
            if power=='encounter':
                actor_ids=re.findall(r'\ba\d+\b',low)
                if len(actor_ids)==2:cmd.update(actor_a=actor_ids[0],actor_b=actor_ids[1])
                else:plan.blocked.append('Часть '+str(index)+': укажите два ID персонажей, например a0 и a3')
            if power=='coordination':
                match=re.search(r'\bg(\d+)\b',low)
                if match:cmd['association_id']='G'+match.group(1)
            plan.commands.append(cmd)
    if not plan.blocked:
        scratch=copy.deepcopy(world.state)
        try:
            for cmd in plan.commands:_,cost=apply_power(scratch,world.data,cmd);plan.cost+=cost
        except RuleError as exc:plan.blocked.append(str(exc))
    plan.notes.append('Меняются обстоятельства. Победитель, поддержка и трактовка события не назначаются.')
    return plan


def execute(world,plan):
    # Reparse text: a caller cannot erase guards by editing Plan fields.
    fresh=parse(world,plan.text)
    if not fresh.ready or fresh.commands!=plan.commands:raise RuleError('\n'.join(fresh.blocked) or 'План изменён: разберите фразу заново')
    scratch=copy.deepcopy(world.state);events=[]
    for cmd in fresh.commands:events.append(apply_power(scratch,world.data,cmd)[0])
    from .world import validate_state
    scratch['revision']+=1;validate_state(scratch,world.data);world.state=scratch
    return events
