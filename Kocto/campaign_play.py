"""Interactive tutorial, dirty actions with traces and rivals that gain or lose
ratings, on top of WorldRuntime.

Data: data/world/play.json. Dirty actions («незаконно …») are stronger and
cost more, but every one leaves a trace. Traces fade slowly; each week the
opposition may find them (deterministic per seed/week). Discovery publishes a
scandal with delayed penalties. Safe actions never create traces.
"""
from __future__ import annotations

import json
import random
from dataclasses import replace
from pathlib import Path

import campaign_world as world
import semantic_runtime as base
from semantic_actions import ActionCard, CardError, Reason

base.REASONS.update({'dirty': 'Грязный метод'})
TUTORIAL = 'semantic_tutorial'
TRACES = 'semantic_traces'
CLEANUP = 'semantic_cleanup_week'


def load_config(path):
    config = world.load_config(path)
    extra = Path(path).with_name('play.json')
    if extra.exists():
        config.update(json.loads(extra.read_text(encoding='utf-8')))
    return config


class PlayRuntime(world.WorldRuntime):
    @classmethod
    def from_file(cls, engine, path, allocation=None):
        return cls(engine, load_config(path), allocation)

    # --- interactive tutorial -----------------------------------------
    def tutorial_steps(self):
        return self.config.get('tutorial_steps', [])

    def step_done(self, state, step, low):
        kind = step['check']
        cards = [qa['semantic_card'] for qa in state.week_actions if 'semantic_card' in qa]
        if kind == 'command':
            return any(low == c or low.startswith(c + ' ') for c in step['commands'])
        if kind == 'pending':
            return base.PENDING in state.parser_context
        if kind == 'queued':
            return bool(cards)
        if kind == 'history':
            return bool(state.world.get(base.HISTORY))
        if kind == 'promise':
            return bool(state.world.get(base.PROMISES)) or any(c['action_type'] == 'promise' for c in cards)
        return False

    def tutorial_advance(self, state, low=''):
        info = state.world.get(TUTORIAL)
        if not info or not info.get('active'):
            return ''
        steps = self.tutorial_steps()
        moved = False
        while info['step'] < len(steps) and self.step_done(state, steps[info['step']], low):
            info['step'] += 1
            moved = True
        if info['step'] >= len(steps):
            info['active'] = False
            info['finished'] = True
            return self.config['tutorial_done']
        prefix = 'Хорошо! ' if moved else ''
        return f'{prefix}Обучение {info["step"] + 1}/{len(steps)}: {steps[info["step"]]["text"]}'

    def tutorial_command(self, state, low):
        info = state.world.setdefault(TUTORIAL, {'step': 0, 'active': False})
        if low == 'обучение выкл':
            info['active'] = False
            return 'Обучение выключено. Вернуть: «обучение», сначала: «обучение заново».'
        if low == 'обучение заново' or info.get('finished') and low == 'обучение':
            info.update(step=0, finished=False)
        info['active'] = True
        return '\n'.join(self.config['tutorial']) + '\n\n' + self.tutorial_advance(state)

    # --- dirty actions ------------------------------------------------
    def validate(self, state, card):
        if card.legality != 'illegal':
            return super().validate(state, card)
        dirty = self.config['dirty']
        if card.action_type not in dirty['types']:
            raise CardError('Незаконный вариант есть только у: '
                            + ', '.join(base.LABELS[t].lower() for t in dirty['types']) + '.')
        spec, cost = super().validate(state, replace(card, legality=''))
        return spec, cost + dirty['extra_cost']

    def evaluate(self, state, card, profile=None):
        result, cost = super().evaluate(state, card, profile)
        if card.legality != 'illegal':
            return result, cost
        dirty, rules = self.config['dirty'], self.config['rules']
        chance = min(rules['max_chance'], result.chance * dirty['chance_factor'])
        return replace(result, chance=round(chance, 3), effect=round(result.effect * dirty['effect_factor'], 3),
                       reasons=result.reasons + (Reason('dirty', dirty['chance_factor'], dirty['effect_factor'],
                                                        'сильнее, но оставляет улики'),)), cost

    def trace_strength(self, card, success):
        weights = self.config['dirty']['trace']
        value = weights['secret' if card['visibility'] == 'secret' else 'public']
        return round(value + (0 if success else weights['failure_bonus']), 3)

    def describe(self, state, card):
        message = super().describe(state, card)
        if card.legality != 'illegal':
            return message
        dirty = self.config['dirty']
        note = (f'ГРЯЗНЫЙ МЕТОД: эффект ×{dirty["effect_factor"]:g}, цена +{dirty["extra_cost"]}. Останется улика '
                f'силой {self.trace_strength(card.to_dict(), True):g} (при неудаче больше). Если её найдут — скандал. '
                'Тайно — меньше следов. Смотри «улики».')
        marker = 'Подтвердить: «подтвердить действие»'
        head, sep, tail = message.partition(marker)
        return head + note + '\n' + sep + tail if sep else message + '\n' + note

    def hidden_traces(self, state):
        return [t for t in state.world.get(TRACES, []) if t['status'] == 'hidden']

    def exposure_risk(self, state):
        dirty = self.config['dirty']
        total = sum(t['strength'] for t in self.hidden_traces(state))
        return min(dirty['max_discovery'], total * dirty['weekly_discovery']) if total else 0.0

    def traces_text(self, state):
        hidden = self.hidden_traces(state)
        if not hidden:
            return 'Улик против тебя нет. Честные действия следов не оставляют.'
        lines = [f'• неделя {t["week"]}: «{t["raw"]}» — сила {t["strength"]:g}' for t in hidden]
        cleanup = self.config['dirty']['cleanup']
        return ('Улики (видишь только ты):\n' + '\n'.join(lines)
                + f'\nРиск разоблачения за неделю: {self.exposure_risk(state) * 100:.0f}%.'
                + f'\n«замести следы» — {cleanup["cost"]} денег, −{cleanup["reduce"]:g} к каждой улике, раз в неделю.')

    def cleanup(self, state, rng):
        cleanup = self.config['dirty']['cleanup']
        hidden = self.hidden_traces(state)
        if not hidden:
            return 'Заметать нечего: улик нет.'
        if state.world.get(CLEANUP) == state.week:
            return 'Следы уже заметали на этой неделе.'
        if state.player.money < cleanup['cost']:
            return 'Недостаточно денег, чтобы замести следы.'
        state.player.money -= cleanup['cost']
        state.world[CLEANUP] = state.week
        for trace in hidden:
            trace['strength'] = round(max(0.0, trace['strength'] - cleanup['reduce']), 3)
            if trace['strength'] < self.config['dirty']['fade_below']:
                trace['status'] = 'faded'
        self.engine.save_game(state, rng)
        return 'Следы заметены.\n' + self.traces_text(state)

    def dirty_after(self, state, review, completed_week):
        dirty = self.config['dirty']
        traces = state.world.setdefault(TRACES, [])
        for trace in traces:  # older traces fade first
            if trace['status'] == 'hidden':
                trace['strength'] = round(trace['strength'] * dirty['fade'], 3)
                if trace['strength'] < dirty['fade_below']:
                    trace['status'] = 'faded'
        rng = random.Random(f'{getattr(state, "seed", 0)}:{completed_week}:dirty')
        exposed = self.hidden_traces(state) and rng.random() < self.exposure_risk(state)
        for item in review:
            card = item['script'].get('semantic_card')
            if card and card.get('legality') == 'illegal':
                traces.append({'week': completed_week, 'raw': card['raw'], 'target_id': card['target_id'],
                               'strength': self.trace_strength(card, item.get('success', False)), 'status': 'hidden'})
        if exposed:
            self.scandal(state)
        state.world[TRACES] = traces[-60:]

    def scandal(self, state):
        rules = self.config['dirty']['scandal']
        found = self.hidden_traces(state)
        found = [t for t in found if t['week'] < state.week - 1] or found
        for trace in found:
            trace['status'] = 'exposed'
            self.adjust(state, trace['target_id'], rules['target_mood'], 0)
        for group in state.groups:
            self.adjust(state, group.id, rules['all_mood'], 0)
        state.player.trust = max(0, state.player.trust + rules['trust'])
        for name in ('evidence', 'investigation'):
            if hasattr(state.player, name):
                setattr(state.player, name, getattr(state.player, name) + rules[name])
        for rival in getattr(state, 'candidates', []):
            if rival.id in self.config.get('rivals', {}):
                self.rival_popularity(rival, rules['rival_popularity'])
        quotes = '; '.join(f'«{t["raw"]}» (неделя {t["week"]})' for t in found)
        self.publish_as(state, 'opposition', f'Улики против кандидата {state.player.name}',
                        'Редакция доказала незаконные методы: ' + quotes + '.', 'semantic_dirty', -0.8)
        self.systems.add_log(state, f'Скандал: доверие {rules["trust"]:+d}, все группы {rules["all_mood"]:+d}, '
                                       f'следствие и улики +{rules["evidence"]}.')

    # --- rivals and their ratings ---------------------------------------
    @staticmethod
    def rival_popularity(rival, delta):
        if hasattr(rival, 'popularity'):
            rival.popularity = max(0, min(100, rival.popularity + delta))

    def rival_support(self, state, rid, group_ids):
        share = self.config['rival_rating']['support_share']
        for group in state.groups:
            if group.id in group_ids and isinstance(getattr(group, 'candidate_support', None), dict):
                gain = max(1, int(getattr(group, 'size', 10) * share))
                group.candidate_support[rid] = group.candidate_support.get(rid, 0) + gain

    def rival_react(self, state, records):
        rating = self.config['rival_rating']
        rivals = {item.id: item for item in getattr(state, 'candidates', [])}
        names = {g.id: g.name for g in state.groups}
        success = getattr(self, '_success', {})
        for data in records:
            card = ActionCard.from_dict(data)
            if card.visibility == 'secret':
                continue
            for rid, spec in self.config.get('rivals', {}).items():
                stance = spec['stances'].get(card.topic)
                if rid not in rivals or not stance:
                    continue
                rival, name = rivals[rid], rivals[rid].name
                audience = [card.target_id] if card.target_kind == 'group' else self.config['audiences'].get(card.target_id, [])
                crossed = [gid for gid in audience if self.hits(card, gid)[1]]
                if crossed:
                    for gid in crossed:
                        self.adjust(state, gid, spec['exploit_mood'], 0)
                    self.rival_popularity(rival, rating['exploit'])
                    self.rival_support(state, rid, crossed)
                    text = (f'{name} пользуется ошибкой: «{card.raw}» задело ' + ', '.join(names.get(g, g) for g in crossed)
                            + f'. Рейтинг {name} {rating["exploit"]:+d}.')
                elif card.stance and card.stance != stance:
                    won = success.get(card.raw, False)
                    delta = rating['debate_lost'] if won else rating['debate_won']
                    self.rival_popularity(rival, delta)
                    if not won:
                        self.rival_support(state, rid, audience)
                    verdict = 'город на стороне кандидата' if won else f'спор выиграл {name}'
                    text = f'{name} спорит: «{spec["lines"][stance]}». Повод — «{card.raw}». Итог: {verdict} (рейтинг {name} {delta:+d}).'
                else:
                    text = f'{name} тоже говорит об этом: «{spec["lines"][stance]}».'
                self.publish_as(state, spec['publication'], f'{name} отвечает кандидату {state.player.name}', text, 'semantic_rival', -0.2)
                return

    def rivals_text(self, state):
        lines = []
        for rival in getattr(state, 'candidates', []):
            spec = self.config.get('rivals', {}).get(rival.id)
            if not spec:
                continue
            stances = ', '.join(f'{"за" if v == "for" else "против"} {t}' for t, v in spec['stances'].items())
            lines.append(f'• {rival.name}: рейтинг {getattr(rival, "popularity", "?")}; позиции: {stances}.')
        return ('Соперники (спорь с ними публично и успешно — их рейтинг падает):\n' + '\n'.join(lines)
                if lines else 'Соперников с позициями пока нет.')

    # --- glue -------------------------------------------------------------
    def finish(self, state, verdicts, rng_unused=None):
        review = list(self.review or [])
        self._success = {item['script']['semantic_card']['raw']: item.get('success', False)
                         for item in review if 'semantic_card' in item['script']}
        week = state.week
        super().finish(state, verdicts, rng_unused)
        self._success = {}
        self.dirty_after(state, review, week)
        hint = self.tutorial_advance(state)
        if hint:
            self.systems.add_log(state, hint)

    def advisor(self, state):
        text = super().advisor(state)
        risk = self.exposure_risk(state)
        if risk:
            text += f'\n• Риск разоблачения грязных дел: {risk * 100:.0f}% в неделю. Смотри «улики».'
        return text

    def new_game(self, *args, **kwargs):
        state, rng = super().new_game(*args, **kwargs)
        state.world[TUTORIAL] = {'step': 0, 'active': True}
        return state, rng

    def handle(self, state, rng, command, memory):
        low = ' '.join((command or '').casefold().split())
        free = self.review is None and not state.is_game_over
        if free and (low == 'обучение' or low.startswith('обучение ')):
            return base.reply(self.tutorial_command(state, low))
        if free and low == 'улики':
            result = base.reply(self.traces_text(state))
        elif free and low == 'замести следы':
            result = base.reply(self.cleanup(state, rng))
        elif free and low == 'рейтинги':
            result = base.reply(self.rivals_text(state))
        else:
            result = super().handle(state, rng, command, memory)
        hint = self.tutorial_advance(state, low) if free else ''
        if hint and isinstance(result, dict) and isinstance(result.get('message'), str):
            result = {**result, 'message': result['message'] + '\n\n' + hint}
        return result
