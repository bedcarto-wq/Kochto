"""Two trusted gods, one authoritative world over existing authenticated TCP.
No arbitrary code, no remote files, no desync by client-side world simulation.
"""
from __future__ import annotations
import copy,json,zlib,base64
from ..engine import RuleError,DataError
from .world import fingerprint,validate_state
from .language import parse,execute
from . import storage


def snapshot(world):
    state=copy.deepcopy(world.state)
    if state['territory']:
        return {'format':'god-shared-zlib','rules':fingerprint(world.data),'state':storage.encode(state)}
    return {'format':'god-shared','rules':fingerprint(world.data),'state':state}


def restore(world,obj):
    try:
        if not isinstance(obj,dict) or set(obj)!={'format','rules','state'} or obj['format'] not in ('god-shared','god-shared-zlib','god-shared-delta') or obj['rules']!=fingerprint(world.data):raise DataError('Неверный сетевой мир / правила')
        if obj['format']=='god-shared-delta':
            record=storage.decode(obj['state'])
            if set(record)!={'base','result','changes'} or record['base']!=fingerprint(world.state) or not isinstance(record['changes'],list) or len(record['changes'])>50000:raise DataError('Сетевое расхождение: требуется полный снимок')
            state=copy.deepcopy(world.state)
            for entry in record['changes']:
                if not isinstance(entry,list) or len(entry)!=2 or not isinstance(entry[0],list) or not 1<=len(entry[0])<=16:raise DataError('Неверный путь сетевого изменения')
                path,value=entry;node=state
                for key in path[:-1]:
                    if not isinstance(node,(dict,list)) or (isinstance(node,list) and (type(key) is not int or not 0<=key<len(node))):raise DataError('Неверный адрес изменения')
                    node=node[key]
                key=path[-1]
                if isinstance(node,list):
                    if type(key) is not int or not 0<=key<len(node):raise DataError('Неверный индекс изменения')
                elif not isinstance(node,dict) or key not in node:raise DataError('Неверный ключ изменения')
                node[key]=value
            if fingerprint(state)!=record['result']:raise DataError('Сетевое изменение не прошло контрольную сумму')
        elif obj['format']=='god-shared-zlib':state=storage.decode(obj['state'])
        else:state=copy.deepcopy(obj['state'])
        validate_state(state,world.data)
    except (KeyError,IndexError,TypeError,ValueError,zlib.error) as exc:raise DataError('Повреждённый сетевой мир: '+str(exc)) from exc
    world.state=state;world.undo_buffer=[]


def update(world,before):
    changes=[]
    def diff(a,b,path):
        if a==b:return
        if isinstance(a,dict) and isinstance(b,dict) and set(a)==set(b):
            for key in sorted(a):diff(a[key],b[key],path+[key])
        elif isinstance(a,list) and isinstance(b,list) and len(a)==len(b):
            for i in range(len(a)):diff(a[i],b[i],path+[i])
        else:changes.append([path,b])
    diff(before,world.state,[]);full=snapshot(world)
    if not changes or len(changes)>50000 or any(not c[0] for c in changes):return full
    delta={'format':'god-shared-delta','rules':fingerprint(world.data),'state':storage.encode({'base':fingerprint(before),'result':fingerprint(world.state),'changes':changes})}
    return delta if len(json.dumps(delta,ensure_ascii=False))<len(json.dumps(full,ensure_ascii=False)) else full


def command(world,revision,op,payload,delta=False):
    if type(revision) is not int or revision!=world.state['revision']:raise RuleError('Мир изменился; дождитесь состояния и повторите разбор')
    before=copy.deepcopy(world.state)
    if op=='plan':
        if not isinstance(payload,str):raise RuleError('Нужен исходный текст')
        plan=parse(world,payload)
        if not plan.ready:raise RuleError('\n'.join(plan.blocked))
        execute(world,plan)
    elif op=='power':world.intervene(payload)
    elif op=='direct':world.direct(payload)
    elif op=='step':world.step(payload,True)
    elif op=='territory':
        if not isinstance(payload,dict) or set(payload)!={'op','value'}:raise RuleError('Неверная операция территории')
        world.territorial_action(payload['op'],payload['value'])
    elif op=='story':
        if not isinstance(payload,dict) or set(payload)!={'op','value'}:raise RuleError('Неверная операция истории')
        world.story_action(payload['op'],payload['value'])
    else:raise RuleError('Неизвестная сетевая операция')
    return update(world,before) if delta else snapshot(world)
