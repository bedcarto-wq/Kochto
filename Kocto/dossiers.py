"""Group dossiers, red lines and opposition-press reactions on top of SemanticRuntime.

Data lives in data/world/dossiers.json. A fear only weakens the effect; a red
line halves the chance, turns the effect negative and, after the week, costs
mood and trust. Public crossings and broken promises are published by the
opposition press. Every factor is shown in the card's reasons.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import semantic_runtime as base
from semantic_actions import ActionCard, CardError, Reason

base.REASONS.update({'fear': 'Опасение адресата', 'red_line': 'Красная линия адресата'})
STANCE = {'for': 'за', 'against': 'против'}
WARNING = ('ВНИМАНИЕ: это красная линия адресата. После недели — штраф к настроению и доверию; '
           'если публично, оппозиционная пресса напишет об этом.')


def load_config(path):
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    extra = Path(path).with_name('dossiers.json')
    if extra.exists():
        config.update(json.loads(extra.read_text(encoding='utf-8')))
    return config


class DossierRuntime(base.SemanticRuntime):
    @classmethod
    def from_file(cls, engine, path, allocation=None):
        return cls(engine, load_config(path), allocation)

    def profile(self, state, kind, target):
        profile = super().profile(state, kind, target)
        if kind == 'group':
            profile = {**profile, '_group': target}
        return profile

    def hits(self, card, group_id):
        dossier = self.config.get('dossiers', {}).get(group_id or '', {})
        match = lambda item: bool(card.stance) and item['topic'] == card.topic and item['stance'] == card.stance
        return ([item for item in dossier.get('fears', []) if match(item)],
                [item for item in dossier.get('red_lines', []) if match(item)])

    def evaluate(self, state, card, profile=None):
        if profile is None:
            self.validate(state, card)
            profile = self.profile(state, card.target_kind, card.target_id)
        result, cost = super().evaluate(state, card, profile)
        fears, lines = self.hits(card, profile.get('_group'))
        if not fears and not lines:
            return result, cost
        rules = self.config['rules']
        chance, effect, reasons = result.chance, result.effect, list(result.reasons)
        for item in fears:
            reasons.append(Reason('fear', 1.0, item['factor'], item['text']))
            effect *= item['factor']
        for item in lines:
            factor = self.config['press']['red_line_chance']
            reasons.append(Reason('red_line', factor, -1.0, item['text']))
            chance *= factor
            effect = -abs(effect)
        if result.chance > 0:
            chance = min(rules['max_chance'], max(rules['min_chance'], chance))
        return replace(result, chance=round(chance, 3), effect=round(effect, 3), reasons=tuple(reasons)), cost

    def describe(self, state, card):
        message = super().describe(state, card)
        result, _ = self.evaluate(state, card)
        extra = [f'{base.REASONS[r.source]}: {r.details}' for r in result.reasons if r.source in ('fear', 'red_line')]
        if any(r.source == 'red_line' for r in result.reasons):
            extra.append(WARNING)
        if not extra:
            return message
        marker = 'Подтвердить: «подтвердить действие»'
        head, sep, tail = message.partition(marker)
        return head + '\n'.join(extra) + '\n' + sep + tail if sep else message + '\n' + '\n'.join(extra)

    def dossier(self, state, name):
        if not name:
            return base.reply('Досье есть на группы: ' + ', '.join(g.name for g in state.groups)
                              + '. Пример: «досье рабочие».')
        key = name.casefold()
        found = [gid for gid, aliases in self.entities(state)['group'].items()
                 if key in [alias.casefold() for alias in aliases]]
        if len(found) != 1:
            raise CardError('Нет досье на такого адресата. Напиши «досье», чтобы увидеть список.')
        gid = found[0]
        group = next(g for g in state.groups if g.id == gid)
        data = self.config.get('dossiers', {}).get(gid, {})
        profile = self.profile(state, 'group', gid)
        top = sorted(profile['issues'].items(), key=lambda item: -item[1])[:4]
        lines = [f'Досье: {group.name} (настроение {group.mood:g})', data.get('summary', ''),
                 'Важные темы: ' + ', '.join(f'{topic} {value:g}' for topic, value in top)]
        if profile.get('positions'):
            lines.append('Позиции: ' + ', '.join(f'{STANCE[v]} {t}' for t, v in profile['positions'].items()))
        if profile.get('channels'):
            lines.append('Каналы: ' + ', '.join(f'{n} ×{v:g}' for n, v in profile['channels'].items()))
        if profile.get('places'):
            lines.append('Места: ' + ', '.join(f'{n} ×{v:g}' for n, v in profile['places'].items()))
        for item in data.get('fears', []):
            lines.append(f'Опасение: {item["text"]} ({STANCE[item["stance"]]} {item["topic"]}) — эффект ×{item["factor"]:g}.')
        for item in data.get('red_lines', []):
            lines.append(f'Красная линия: {item["text"]} ({STANCE[item["stance"]]} {item["topic"]}) — '
                         f'шанс ×{self.config["press"]["red_line_chance"]:g}, эффект в минус; после недели '
                         'штраф, а если действие публичное — статья оппозиционной прессы.')
        return base.reply('\n'.join(line for line in lines if line))

    def handle(self, state, rng, command, memory):
        low = (command or '').strip().casefold()
        if self.review is None and not state.is_game_over and (low == 'досье' or low.startswith('досье ')):
            try:
                return self.dossier(state, command.strip()[len('досье'):].strip())
            except CardError as exc:
                return base.reply(str(exc))
        return super().handle(state, rng, command, memory)

    def publish(self, state, headline, text):
        clipping = {'archive_no': state.next_archive_no, 'week': state.week,
                    'publication': self.config['press']['publication'], 'headline': headline,
                    'lead': text, 'body': text, 'reason': text, 'tone': -0.5, 'source': 'semantic_press'}
        state.next_archive_no += 1
        state.clippings.append(clipping)
        state.clippings[:] = state.clippings[-40:]
        state.news_feed.append(clipping)
        state.news_feed[:] = state.news_feed[-30:]
        self.systems.add_log(state, 'Пресса: ' + headline)

    def finish(self, state, verdicts, rng_unused=None):
        records = [item['script']['semantic_card'] for item in (self.review or [])
                   if 'semantic_card' in item['script']]
        super().finish(state, verdicts, rng_unused)
        self.press_react(state, records)

    def press_react(self, state, records):
        press = self.config['press']
        names = {g.id: g.name for g in state.groups}
        for data in records:
            card = ActionCard.from_dict(data)
            audience = ([card.target_id] if card.target_kind == 'group'
                        else self.config['audiences'].get(card.target_id, []))
            for gid in audience:
                for item in self.hits(card, gid)[1]:
                    self.adjust(state, gid, press['red_line']['group_mood'], press['red_line']['trust'])
                    self.systems.add_log(state, f'{names.get(gid, gid)}: перейдена красная линия — {item["text"]}.')
                    if card.visibility != 'secret':
                        self.publish(state, f'Кандидат {state.player.name} против своих избирателей?',
                                     f'{names.get(gid, gid)} возмущены: {item["text"]}. Цитата: «{card.raw}».')

    def track_promises(self, state, records, week):
        before = {id(p) for p in state.world.get(base.PROMISES, []) if p.get('applied')}
        super().track_promises(state, records, week)
        if not self.config['press'].get('broken_promise'):
            return
        for promise in state.world.get(base.PROMISES, []):
            if promise['status'] == 'broken' and promise.get('applied') and id(promise) not in before:
                self.publish(state, 'Обещание не выполнено',
                             f'Кандидат {state.player.name} обещал: «{promise["text"]}». Итог: {promise["reason"]}.')
