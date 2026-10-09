"""Two trusted gods, one authoritative world over existing authenticated TCP.
No arbitrary code, no remote files, no desync by client-side world simulation.
"""
from __future__ import annotations
import copy
from ..engine import RuleError,DataError
from .world import fingerprint,validate_state
from .language import parse,execute


def snapshot(world):
    return {'format':'god-shared','rules':fingerprint(world.data),'state':copy.deepcopy(world.state)}


def restore(world,obj):
    try:
        if not isinstance(obj,dict) or set(obj)!={'format','rules','state'} or obj['format']!='god-shared' or obj['rules']!=fingerprint(world.data):raise DataError('Неверный сетевой мир / правила')
        state=copy.deepcopy(obj['state']);validate_state(state,world.data)
    except (KeyError,TypeError,ValueError) as exc:raise DataError('Повреждённый сетевой мир: '+str(exc)) from exc
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
    else:raise RuleError('Неизвестная сетевая операция')
    return snapshot(world)
