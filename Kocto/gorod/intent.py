"""Typed semantic front-end; language suggestions never bypass engine rules."""
from __future__ import annotations
import copy
import re
from dataclasses import asdict, dataclass, field
from typing import Optional
from . import engine as E
from . import parser as P

@dataclass
class Predicate:
    kind: str
    proposal: str
    side: int
    text: str

@dataclass
class Step:
    text: str
    span: list
    card: Optional[E.Card]
    source: str = ''
    confidence: float = 0.0
    evidence: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    ambiguities: dict = field(default_factory=dict)
    condition: Optional[Predicate] = None
    blocked: list = field(default_factory=list)
    speech_act: str = 'instruction'

@dataclass
class Intent:
    text: str
    steps: list = field(default_factory=list)
    blocked: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    def record(self):
        return asdict(self)

def _norm(text):
    return text.lower().replace('ё', 'е')

def clauses(data, text):
    seq = '|'.join(re.escape(x) for x in data['intents']['sequences'])
    stems = [re.escape(x) for values in data['lexicon']['actions'].values() for x in values if ' ' not in x]
    action = r'(?:я\s+)?(?:'+'|'.join(sorted(set(stems),key=len,reverse=True))+r')[а-яa-z]*\b'
    separator = re.compile(r';|\b(?:'+seq+r')\b\s*|\s+и\s+(?='+action+r')|,\s*(?='+action+r')',re.I)
    offsets, start = [], 0
    for match in separator.finditer(text):
        if match.group().lstrip().startswith(',') and _norm(text[start:]).lstrip().startswith('если '):
            continue
        offsets.append((start,match.start())); start=match.end()
    offsets.append((start,len(text)))
    out=[]
    for a,b in offsets:
        segment=text[a:b]
        a+=re.match(r'[\s,]*(?:сначала\s+)?',segment,re.I).end()
        b-=len(segment)-len(segment.rstrip(' ,'))
        if a<b: out.append((text[a:b],(a,b)))
    return out

def _guard(step):
    text=_norm(step.text)
    guards=[
        (r'^(?:я\s+)?не\s+(?:хочу|буду|намерен|собираюсь)\b','Отрицание намерения: это не команда.'),
        (r'^(?:я\s+)?(?:хочу\s+узнать|расскажи|объясни)\b','Это вопрос или запрос объяснения, не команда.'),
        (r'\b(?:не\s+(?:буду\s+)?(?:обеща|пообеща|клян|гарантир|встре|выступ|наним|найм|внес|заяв|приму|принима|соглас)[а-я]*|отказываюсь\s+обещать)\b','Отрицание относится к действию: оно не будет исполнено.'),
        (r'\b(?:что\s+(?:будет|если)|как\s+(?:можно|лучше)|почему|можно\s+ли|стоит\s+ли|предположим|допустим|мечтаю|интересно)\b|\?','Это вопрос или гипотеза, не команда.'),
        (r'^(?:он|она|ложкин|соперник|председатель|редактор|директор)\s+(?:не\s+)?(?:будет\s+)?(?:обещ|поддерж|встре|заяв|наним|внес)[а-я]*\b','Это действие другого участника, не команда игрока.'),
        (r'[«»"“”]|\b(?:он|она|ложкин|соперник)\b.{0,60}\b(?:сказал|сказала|обещал|обещала|заявил|заявила|хочет)\b','Цитата или чужое высказывание: не считаю его вашим действием.'),
        (r'\b(?:обещал|обещала|пообещал|пообещала|встретился|встретилась|заявил|заявила)\b','Это сообщение о прошлом, не новое действие.'),
        (r'\b(?:когда|после\s+того\s+как|иначе|либо|если\s+не)\b','Временная зависимость или альтернативная ветка пока не поддерживается.'),
        (r'\b(?:но|однако|кроме|за\s+исключением)\b','Оговорка меняет смысл: уточните отдельные действия, она не будет отброшена.'),
        (r'\d+\s*%|\b(?:рубл|миллион|миллиард|процент)[а-я]*\b','Количественные условия пока не моделируются и не будут заменены обычной позицией.')]
    for pattern,reason in guards:
        if re.search(pattern,text):step.blocked.append(reason)
    if any('вопрос' in x for x in step.blocked):step.speech_act='query'
    elif any('Цитата' in x for x in step.blocked):step.speech_act='reported'
    elif any('Отрицание' in x for x in step.blocked):step.speech_act='denied'

def _predicate(data,text):
    toks=P.tokens(text);entities=P._entities(data,toks)
    props=list(dict.fromkeys(e[2] for e in entities if e[1]=='proposal'))
    if len(props)!=1 or not any(any(t.startswith(x) for x in data['intents']['policy_done']) for t in toks):return None
    if re.search(r'\b(?:будет|будут|станет|поставит|сохранит|пообещает|работа|фильтр)[а-я]*\b',_norm(text)):return None
    aliases=[a.split() for a in data['proposals'][props[0]]['aliases']]
    allowed_stems=[part for alias in aliases for part in alias]+data['intents']['policy_done']+['совет','решени','замороз','город','расшир','сбор','ремонт','дорог','завод','тариф']
    stop={'уже','по','о','об','на','в','за','против','действительно','это','было','были'}
    if any(t not in stop and not any(t.startswith(a) for a in allowed_stems) for t in toks):return None
    side,_=P._side(data,toks)
    return Predicate('policy',props[0],side,text.strip(' ,'))

def analyze(data,text,state=None):
    if not isinstance(text,str) or not text.strip():return Intent(str(text or ''),blocked=['Пустая фраза.'])
    intent=Intent(text)
    if len(text)>data['intents']['max_text']:
        intent.blocked.append('Фраза слишком длинная: максимум '+str(data['intents']['max_text'])+' символов.');return intent
    pieces=clauses(data,text)
    if len(pieces)>data['intents']['max_steps']:
        intent.blocked.append('В плане не более '+str(data['intents']['max_steps'])+' операций. Разделите его.');return intent
    for raw,span in pieces:
        step=Step(raw,list(span),None);_guard(step);main=raw
        if re.search(r'\bесли\b',_norm(raw)):
            if len(re.findall(r'\bесли\b',_norm(raw)))!=1:step.blocked.append('Вложенные условия пока не поддерживаются.')
            elif _norm(raw).lstrip().startswith('если '):
                if ',' not in raw:step.blocked.append('Отделите условие запятой от команды.')
                else:
                    condition,main=raw.split(',',1);step.condition=_predicate(data,condition[5:])
            else:
                main,condition=re.split(r'\bесли\b',raw,maxsplit=1,flags=re.I);step.condition=_predicate(data,condition)
            if step.condition is None:step.blocked.append('Неизвестное условие: не превращаю его в безусловное действие. Поддержано только уже принятое решение по известному вопросу.')
        parsed=P.parse(data,main,state.learned if state else None)
        step.card=parsed.card;step.source=parsed.source;step.confidence=parsed.confidence;step.notes=list(parsed.notes)
        classifier=P.model(data,state.learned if state else None)
        scores=classifier.predict(P.tokens(main)) if classifier else None
        if scores:
            step.evidence.append({'field':'classifier','source':'локальная нейросеть MLP',
                                  'candidates':[{'action':a,'score':round(v,4)} for a,v in sorted(scores.items(),key=lambda x:(-x[1],x[0]))[:3]],
                                  'note':'Оценки классификатора, не вероятность успеха хода; правила имеют приоритет.'})
        lower=_norm(main)
        is_accept=any(lower.strip().startswith(_norm(x)) for x in data['intents']['accept_phrases'])
        if is_accept:
            step.card=E.Card('accept_deal',text=main)
            entities=P._entities(data,P.tokens(main));props=list(dict.fromkeys(e[2] for e in entities if e[1]=='proposal'))
            if len(props)==1:step.card.proposal=props[0]
            elif state and len([d for d in state.negotiations if d['status']=='offered' and state.week<=d['expires_week']])>1:
                step.ambiguities['proposal']=[d['proposal'] for d in state.negotiations if d['status']=='offered' and state.week<=d['expires_week']]
            if state:
                offer=E.open_offer(state,step.card.proposal)
                if offer and 'proposal' not in step.ambiguities:
                    step.card.proposal=offer['proposal'];step.card.side=offer['side']
            step.source='смысловая структура';step.confidence=1.0;step.notes=[];step.speech_act='acceptance'
        elif 'председател' in lower and any(x in lower for x in ('переговор','договор','обсуд','поговор','предлож')):
            if step.card:
                step.card.action='negotiate';step.card.deadline=P._deadline(data,P.tokens(main)) or data['actions']['negotiate']['default_deadline']
            step.source='смысловая структура';step.speech_act='offer'
        if step.card and step.card.action=='negotiate' and step.speech_act!='offer':
            step.blocked.append('Назван председатель, но намерение переговоров не выражено. Опишите предложение явно.')
        if step.card:
            step.card.text=main.strip();entities=P._entities(data,P.tokens(main))
            for kind in ('group','proposal','paper'):
                candidates=list(dict.fromkeys(e[2] for e in entities if e[1]==kind))
                relevant=kind in data['actions'][step.card.action]['requires'] or step.card.action=='interview' or (step.card.action=='accept_deal' and kind=='proposal')
                if len(candidates)>1 and relevant:step.ambiguities[kind]=candidates;setattr(step.card,kind,'')
            if step.card.proposal and step.card.action in ('statement','promise','initiative','negotiate','interview'):
                _,explicit=P._side(data,P.tokens(main))
                if not explicit:
                    step.card.side=0;step.ambiguities['side']=[-1,1];step.notes=[n for n in step.notes if 'считаю «ЗА»' not in n]
            if any('несколько действий' in n for n in parsed.notes) and (step.card.action not in ('negotiate','accept_deal') or any(a in ('interview','promise','initiative','security','publicize') for a in parsed.alternatives)):
                step.blocked.append('Несколько несвязанных операций: разделите их «затем» или точкой с запятой.')
            if parsed.source=='догадка' and step.card.action not in ('accept_deal','negotiate'):step.ambiguities['action']=list(data['actions'])
            remembered=[x for x in (state.intent_memory if state else []) if x.get('text')==P._norm(main)]
            if remembered and not step.blocked:
                try:
                    memory_card=E.Card(**remembered[-1]['card']);validate_card(data,memory_card)
                    step.card=memory_card;step.card.text=main.strip();step.ambiguities.clear();step.source='память'
                except (E.RuleError,TypeError,KeyError):step.notes.append('устаревшая запись памяти не применена')
            step.evidence.append({'field':'action','span':list(span),'text':raw,'source':step.source,'confidence':step.confidence})
            if step.card.action=='promise':step.speech_act='commitment'
        else:step.blocked.append('Не найдено исполнимое намерение.')
        intent.steps.append(step)
    intent.edges=[{'from':i,'to':i+1,'relation':'then'} for i in range(len(intent.steps)-1)]
    return intent

def validate_card(data,card):
    if not isinstance(card,E.Card) or card.action not in data['actions']:raise E.RuleError('Неизвестная операция')
    for key in ('side','deadline'):
        if type(getattr(card,key)) is not int:raise E.RuleError('Позиция и срок должны быть целыми')
    if card.side not in (-1,0,1):raise E.RuleError('Неверная позиция')
    for slot,table in (('group','groups'),('proposal','proposals'),('paper','papers')):
        value=getattr(card,slot)
        if not isinstance(value,str) or (value and value not in data[table]):raise E.RuleError('Неизвестный '+slot)
    if not isinstance(card.text,str) or len(card.text)>data['intents']['max_text']:raise E.RuleError('Неверный текст операции')
    if E.missing_slots(data,card):raise E.RuleError('Нужно уточнить: '+', '.join(E.missing_slots(data,card)))
    if card.action in ('promise','negotiate'):
        default=data['actions'][card.action]['default_deadline']
        if not 1<=(card.deadline or default)<=data['actions'][card.action]['max_deadline']:raise E.RuleError('Неверный срок обязательства')

def condition_ok(state,predicate):
    if predicate is None:return True
    if predicate.kind!='policy' or predicate.side not in (-1,1):raise E.RuleError('Неподдерживаемое условие')
    return state.policies.get(predicate.proposal)==predicate.side

def compile_intent(state,data,intent):
    reasons=list(intent.blocked);cards=[];conditions=[]
    for n,step in enumerate(intent.steps,1):
        reasons+=[f'Шаг {n}: '+s for s in step.blocked]
        if step.ambiguities:reasons.append(f'Шаг {n}: уточните '+', '.join(step.ambiguities))
        try:
            validate_card(data,step.card)
            if step.card.action=='accept_deal' and not E.open_offer(state, step.card.proposal):
                raise E.RuleError('Нет предложения председателя: сначала получите и прочитайте его условия')
            cards.append(copy.deepcopy(step.card));conditions.append(step.condition)
            if not condition_ok(state,step.condition):reasons.append(f'Шаг {n}: условие пока не выполнено — '+step.condition.text)
        except E.RuleError as exc:reasons.append(f'Шаг {n}: '+str(exc))
    if not intent.steps:reasons.append('Нет операций')
    if len(intent.steps)>state.actions_left:reasons.append('Не хватает действий на весь план')
    if cards and sum(data['actions'][c.action]['cost'] for c in cards)>state.money:reasons.append('Не хватает денег на весь план')
    if reasons:raise E.RuleError('\n'.join(dict.fromkeys(reasons)))
    return cards,conditions

def remember(state,data,intent):
    record=intent.record();record['week']=state.week;state.intent_history.append(record)
    del state.intent_history[:-data['intents']['history_limit']]
    for step in intent.steps:
        if step.card and step.text.strip():state.intent_memory.append({'text':P._norm(step.card.text or step.text),'card':asdict(step.card)})
    del state.intent_memory[:-data['intents']['memory_limit']]
