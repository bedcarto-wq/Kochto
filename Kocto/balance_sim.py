"""Automated balance simulation on the deterministic fake engine.

Runs three strategies (passive / honest / dirty) for many seeds and reports
mood, trust, scandals, the observed chance range and the catastrophe rate of
safe actions. It measures the semantic layer (situations, chains, rivals,
passivity, dirty traces); it does NOT measure the full engine's elections.
Usage: python balance_sim.py [weeks] [seeds]  -> prints a table, writes BALANCE.md
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT))

GROUP_PHRASE = {
    'workers': 'встретиться с рабочими о работе',
    'doctors': 'встретиться с врачами о медицине',
    'elders': 'встретиться с пенсионерами о жкх',
    'teachers': 'встретиться с учителями об образовании',
    'youth': 'встретиться с молодежью об интернете',
    'business': 'встретиться с предпринимателями о налогах',
}
STRATEGIES = ('passive', 'honest', 'dirty')


def make_harness(seed):
    import test_chains
    from campaign_chains import ChainRuntime, load_config
    case = test_chains.ChainTests('test_all_chain_advice_phrases_parse')
    case.setUp()
    case.all_groups()
    case.runtime.uninstall()
    case.config = load_config(ROOT / 'data/world/semantic.json')  # real values, no test overrides
    case.runtime = ChainRuntime(case.engine, case.config)
    case.runtime.install()
    case.state.seed = seed
    case.state.player.money = 10 ** 7
    case.rng.seed(seed)
    return case


def plan(case, strategy, rng):
    if strategy == 'passive':
        return []
    runtime, state = case.runtime, case.state
    phrases = []
    specs = runtime.chain_specs()
    for item in runtime.chain_state(state)['active']:
        step = specs[item['id']]['steps'][item['step']]
        if item.get('announced') and step.get('advice'):
            phrases.append(step['advice'])
    for spec, _ in runtime.active_situations(state):
        phrases.append(spec['advice'])
    worst = sorted(state.groups, key=lambda g: g.mood)
    phrases += [GROUP_PHRASE[g.id] for g in worst if g.id in GROUP_PHRASE]
    phrases = list(dict.fromkeys(phrases))[:2]
    if strategy == 'dirty':
        phrases = ['незаконно ' + p for p in phrases]
    return phrases


def run(strategy, seed, weeks):
    from semantic_runtime import PENDING
    case = make_harness(seed)
    rng = random.Random(seed)
    state = case.state
    chances, drops, clean_weeks = [], 0, 0
    for _ in range(weeks):
        for phrase in plan(case, strategy, rng):
            case.say(phrase)
            if state.parser_context.get(PENDING):
                case.say('подтвердить действие')
        for qa in state.week_actions:
            chances.append(qa['semantic_evaluation']['chance'])
            qa['semantic_evaluation']['chance'] = qa['semantic_evaluation']['chance'] if rng.random() * 100 < qa['semantic_evaluation']['chance'] else 0
            if qa['semantic_evaluation']['chance']:
                qa['semantic_evaluation']['chance'] = 100
        clean = state.week_actions and all(qa['semantic_card'].get('legality') != 'illegal' for qa in state.week_actions)
        before = {g.id: g.mood for g in state.groups}
        case.engine.systems.begin_week_end(state)
        case.engine.systems.finish_week(state, [])
        if clean:
            clean_weeks += 1
            if any(before[g.id] - g.mood >= 15 for g in state.groups):
                drops += 1
    moods = [g.mood for g in state.groups]
    return {
        'mood': sum(moods) / len(moods), 'min_mood': min(moods), 'trust': state.player.trust,
        'scandals': sum(1 for c in state.clippings if c.get('source') == 'semantic_dirty'),
        'evidence': getattr(state.player, 'evidence', 0),
        'chains_ok': sum(1 for v in state.world.get('semantic_chains', {}).get('done', {}).values() if v['result'] == 'success'),
        'chance_min': min(chances) if chances else None, 'chance_max': max(chances) if chances else None,
        'catastrophe_rate': drops / clean_weeks if clean_weeks else 0.0,
    }


def simulate(weeks=48, seeds=20):
    table = {}
    for strategy in STRATEGIES:
        rows = [run(strategy, seed, weeks) for seed in range(seeds)]
        avg = lambda key: sum(r[key] for r in rows) / len(rows)
        mins = [r['chance_min'] for r in rows if r['chance_min'] is not None]
        maxs = [r['chance_max'] for r in rows if r['chance_max'] is not None]
        table[strategy] = {
            'mood': round(avg('mood'), 1), 'min_mood': round(avg('min_mood'), 1), 'trust': round(avg('trust'), 1),
            'scandals': round(avg('scandals'), 2), 'evidence': round(avg('evidence'), 1), 'chains_ok': round(avg('chains_ok'), 2),
            'chance_min': min(mins) if mins else None, 'chance_max': max(maxs) if maxs else None,
            'catastrophe_rate': round(avg('catastrophe_rate'), 4),
        }
    return table


def report(table, weeks, seeds):
    cols = ['mood', 'min_mood', 'trust', 'scandals', 'evidence', 'chains_ok', 'chance_min', 'chance_max', 'catastrophe_rate']
    lines = ['# Баланс: автоматическая симуляция', '',
             f'{weeks} недель × {seeds} сидов, фейковый движок (смысловой слой: ситуации, цепочки, соперники, '
             'пассивность, грязные следы). Выборы полного движка здесь НЕ считаются — это для ручного плейтеста.', '',
             '| стратегия | ' + ' | '.join(cols) + ' |', '|' + '---|' * (len(cols) + 1)]
    for name, row in table.items():
        lines.append(f'| {name} | ' + ' | '.join(str(row[c]) for c in cols) + ' |')
    lines += ['', 'Цели: honest > passive по настроению; шансы 15–90; катастрофы от чистых действий ≤2%; '
              'у грязной стратегии больше улик и скандалов.', '']
    return '\n'.join(lines)


if __name__ == '__main__':
    weeks = int(sys.argv[1]) if len(sys.argv) > 1 else 48
    seeds = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    table = simulate(weeks, seeds)
    text = report(table, weeks, seeds)
    print(text)
    (ROOT / 'BALANCE.md').write_text(text, encoding='utf-8')
