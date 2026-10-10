"""Two trusted gods, one authoritative world over existing authenticated TCP.
No arbitrary code, no remote files, no desync by client-side world simulation.
"""
from __future__ import annotations
import copy,json,zlib,base64
from ..engine import RuleError,DataError
from .world import fingerprint,validate_state
from .language import parse,execute


def snapshot(world):
    state=copy.deepcopy(world.state)
    if state['territory']:
        raw=json.dumps(state,ensure_ascii=False,separators=(',',':')).encode()
        if len(raw)>20_000_000:raise DataError('Сетевой мир превышает ограничение 20 МБ')
        return {'format':'god-shared-zlib','rules':fingerprint(world.data),'state':base64.b64encode(zlib.compress(raw,6)).decode()}
    return {'format':'god-shared','rules':fingerprint(world.data),'state':state}


def restore(world,obj):
    try:
        if not isinstance(obj,dict) or set(obj)!={'format','rules','state'} or obj['format'] not in ('god-shared','god-shared-zlib') or obj['rules']!=fingerprint(world.data):raise DataError('Неверный сетевой мир / правила')
        if obj['format']=='god-shared-zlib':
            if not isinstance(obj['state'],str) or len(obj['state'])>5_000_000:raise DataError('Слишком большой сжатый снимок')
            compressed=base64.b64decode(obj['state'],validate=True);dec=zlib.decompressobj();raw=dec.decompress(compressed,20_000_001)
            if len(raw)>20_000_000 or not dec.eof or dec.unused_data:raise DataError('Неверный размер сжатого снимка')
            state=json.loads(raw)
        else:state=copy.deepcopy(obj['state'])
        validate_state(state,world.data)
    except (KeyError,TypeError,ValueError,zlib.error) as exc:raise DataError('Повреждённый сетевой мир: '+str(exc)) from exc
    world.state=state;world.undo_buffer=[]


def command(world,revision,op,payload):
    if type(revision) is not int or revision!=world.state['revision']:raise RuleError('Мир изменился; дождитесь состояния и повторите разбор')
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
    return snapshot(world)
