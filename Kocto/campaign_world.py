"""Living city on top of DossierRuntime: situations, rival replies, passivity,
an out-of-world advisor and a tutorial.

Data: data/world/campaign.json. Everything here is deterministic per campaign
seed and week, so a reloaded week replays the same situation.
"""
from __future__ import annotations

import json
import random
from dataclasses import replace
from pathlib import Path

import dossiers
import semantic_runtime as base
from semantic_actions import ActionCard, Reason

base.REASONS.update({'situation': 'Городская ситуация'})
SITUATIONS = 'semantic_situations'
PASSIVE = 'semantic_passive_weeks'
COMMANDS = ('ситуации', 'советник', 'обучение')


def load_config(path):
    config = dossiers.load_config(path)
    extra = Path(path).with_name('campaign.json')
    if extra.exists():
        config.update(json.loads(extra.read_text(encoding='utf-8')))
    return config


class WorldRuntime(dossiers.DossierRuntime):
    @classmethod
    def from_file(cls, engine, path, allocation=None):
        return cls(engine, load_config(path), allocation)

    # --- situations -------------------------------------------------------
    def situation_specs(self):
        return {item['id']: item for item in self.config.get('situations', [])}

    def active_situations(self, state):
        specs = self.situation_specs()
        return [(specs[item['id']], item) for item in state.world.get(SITUATIONS, [])
                if item['until'] >= state.week and item['id'] in specs]

    def evaluate(self, state, card, profile=None):
        result, cost = super().evaluate(state, card, profile)
        for spec, _ in self.active_situations(state):
            if spec['topic'] == card.topic and (card.target_kind != 'group' or card.target_id in spec['groups']):
                bonus = self.config['situation_effect_bonus']
                result = replace(result, effect=round(result.effect * bonus, 3),
                                 reasons=result.reasons + (Reason('situation', 1.0, bonus, spec['title']),))
                break
        return result, cost

    def start_situation(self, state, completed_week):
        active = self.active_situations(state)
        if active or not self.config.get('situations'):
            return None
        rng = random.Random(f'{getattr(state, "seed", 0)}:{completed_week}:situation')
        if rng.random() >= self.config['situation_chance']:
            return None
        recent = {item['id'] for item in state.world.get(SITUATIONS, [])[-4:]}
        pool = [item for item in self.config['situations'] if item['id'] not in recent] or self.config['situations']
        spec = rng.choice(pool)
        until = state.week + spec['weeks'] - 1
        state.world[SITUATIONS] = (state.world.get(SITUATIONS, []) + [{'id': spec['id'], 'week': state.week, 'until': until}])[-30:]
        if spec.get('event'):
            hot = state.world.setdefault('hot_groups', {})
            label = self.config['event_labels'][spec['event']][0]
            for gid in spec['groups']:
                hot[gid] = {'event': label, 'until': until}
        self.publish_as(state, spec.get('publication', 'independent'), spec['title'], spec['text'], 'semantic_situation', 0.0)
        return spec

    # --- rivals -----------------------------------------------------------
    def rival_react(self, state, records):
        rivals = {item.id: item for item in getattr(state, 'candidates', [])}
        names = {g.id: g.name for g in state.groups}
        for data in records:
            card = ActionCard.from_dict(data)
            if card.visibility == 'secret':
                continue
            for rid, spec in self.config.get('rivals', {}).items():
                stance = spec['stances'].get(card.topic)
                if rid not in rivals or not stance:
                    continue
                name = rivals[rid].name
                crossed = [gid for gid in ([card.target_id] if card.target_kind == 'group' else self.config['audiences'].get(card.target_id, []))
                           if self.hits(card, gid)[1]]
                if crossed:
                    for gid in crossed:
                        self.adjust(state, gid, spec['exploit_mood'], 0)
                    text = f'{name} пользуется ошибкой: «{card.raw}» задело ' + ', '.join(names.get(g, g) for g in crossed) + '.'
                elif card.stance and card.stance != stance:
                    text = f'{name} спорит: «{spec["lines"][stance]}». Повод — «{card.raw}».'
                else:
                    text = f'{name} тоже говорит об этом: «{spec["lines"][stance]}».'
                self.publish_as(state, spec['publication'], f'{name} отвечает кандидату {state.player.name}', text, 'semantic_rival', -0.2)
                return  # one rival reply per week keeps the feed readable

    # --- passivity --------------------------------------------------------
    def passivity(self, state, acted):
        rules = self.config['passivity']
        weeks = 0 if acted else state.world.get(PASSIVE, 0) + 1
        state.world[PASSIVE] = weeks
        if weeks > rules['grace_weeks']:
            for group in state.groups:
                self.adjust(state, group.id, rules['group_mood'], 0)
            self.systems.add_log(state, f'Ты бездействуешь {weeks} нед. подряд: все группы {rules["group_mood"]:+g} к настроению.')
            if weeks == rules['grace_weeks'] + 1:
                self.publish_as(state, 'opposition', f'Где кандидат {state.player.name}?',
                                'Несколько недель без встреч и заявлений: город начинает забывать.', 'semantic_passive', -0.4)

    def publish_as(self, state, publication, headline, text, source, tone):
        clipping = {'archive_no': state.next_archive_no, 'week': state.week, 'publication': publication,
                    'headline': headline, 'lead': text, 'body': text, 'reason': text, 'tone': tone, 'source': source}
        state.next_archive_no += 1
        state.clippings.append(clipping)
        state.clippings[:] = state.clippings[-40:]
        state.news_feed.append(clipping)
        state.news_feed[:] = state.news_feed[-30:]
        self.systems.add_log(state, 'Пресса: ' + headline)

    def finish(self, state, verdicts, rng_unused=None):
        review = self.review or []
        records = [item['script']['semantic_card'] for item in review if 'semantic_card' in item['script']]
        week = state.week
        super().finish(state, verdicts, rng_unused)
        self.rival_react(state, records)
        self.passivity(state, bool(review))
        self.start_situation(state, week)

    # --- out-of-world helpers -------------------------------------------
    def situations_text(self, state):
        active = self.active_situations(state)
        if not active:
            return 'Сейчас в городе спокойно. Ситуации появляются после завершения недели.'
        return '\n'.join(f'• {spec["title"]} (до недели {item["until"]}): {spec["text"]} '
                          f'Действия на тему сильнее ×{self.config["situation_effect_bonus"]:g}. Пример: «{spec["advice"]}».'
                          for spec, item in active)

    def advisor(self, state):
        tips = []
        for spec, item in self.active_situations(state):
            tips.append(f'Ситуация «{spec["title"]}»: попробуй «{spec["advice"]}».')
        for promise in state.world.get(base.PROMISES, []):
            if promise['status'] == 'active' and promise['deadline'] - state.week <= 3:
                tips.append(f'Обещание «{promise["text"]}» истекает на неделе {promise["deadline"]}: нужно дело по той же теме и с той же позицией.')
        if state.groups:
            worst = min(state.groups, key=lambda g: g.mood)
            tips.append(f'Хуже всего к тебе относятся: {worst.name} ({worst.mood:g}). Смотри «досье {worst.name.casefold()}» — там их темы и красные линии.')
        if state.world.get(PASSIVE, 0) >= self.config['passivity']['grace_weeks']:
            tips.append('Ты давно ничего не делал: ещё одна пустая неделя — и все группы начнут остывать.')
        calendar = self.config['calendar']
        election = getattr(state, 'next_election_week', calendar['first_election_week'])
        tips.append(f'Календарь: неделя {state.week}, ближайшие выборы — неделя {election}, цель — стать мэром к неделе {calendar["goal_week"]}.')
        return 'Советник (вне игрового мира, ничего не тратит):\n' + '\n'.join('• ' + tip for tip in tips)

    def handle(self, state, rng, command, memory):
        low = ' '.join((command or '').casefold().split())
        if self.review is None and not state.is_game_over and low in COMMANDS:
            if low == 'ситуации':
                return base.reply(self.situations_text(state))
            if low == 'советник':
                return base.reply(self.advisor(state))
            return base.reply('\n'.join(self.config['tutorial']))
        return super().handle(state, rng, command, memory)
