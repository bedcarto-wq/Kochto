"""Confirmed semantic actions integrated through reversible engine hooks.

First live slice: meeting, interview, volunteer_work. Other catalog buttons
remain legacy. Free-form unsupported input NEVER falls back to tag guessing.
Effects are generated here but applied only by the engine's finish_week.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

from semantic_actions import ActionCard, ActionContext, CardError, Evidence, evaluate_action
from semantic_parser import parse_action

KEY = '__semantic_cards__'
PENDING = 'pending_semantic'
HISTORY = 'semantic_history'
LABELS = {'meeting': 'Встреча', 'interview': 'Интервью', 'volunteer_work': 'Субботник'}
REASONS = {'topic_target': 'Тема и интересы адресата', 'channel_target': 'Канал общения',
           'place_time': 'Место и событие', 'method_goal': 'Способ и цель',
           'resources_scale': 'Ресурсы', 'consistency': 'Последовательность позиции',
           'repetition': 'Повтор', 'creativity': 'Связанные детали'}
SERVICE = {'', '0', '1', '2', '3', '4', '5', '6', '7', 'я', 'me', 'партии', 'parties',
           'пресса', 'press', 'журнал', 'log', 'справка', 'help', 'управление', 'gov',
           'город', 'соперники', 'world', 'преодолеть вето', 'забыть обещание', 'скрыть обещание'}


def reply(message):
    return {'message': message, 'modal': None, 'review': None}


class SemanticRuntime:
    def __init__(self, engine, config):
        self.engine = engine
        self.systems = engine.systems
        self.config = copy.deepcopy(config)
        self.original = []
        self.review = None

    @classmethod
    def from_file(cls, engine, path):
        return cls(engine, json.loads(Path(path).read_text(encoding='utf-8')))

    def fingerprint(self):
        data = self.systems.DATA
        payload = [self.config, getattr(data, 'dictionaries', {})]
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def cache(self, memory):
        fingerprint = self.fingerprint()
        entry = memory.get(KEY)
        if not isinstance(entry, dict) or entry.get('fingerprint') != fingerprint:
            entry = {'fingerprint': fingerprint, 'cards': {}}
            memory[KEY] = entry
        if not isinstance(entry.get('cards'), dict):
            entry['cards'] = {}
        return entry['cards']

    @staticmethod
    def phrase_key(text):
        return ' '.join(text.casefold().split())  # negation/prepositions stay

    def entities(self, state):
        result = {}
        for kind, attribute in (('group', 'groups'), ('publication', 'publications'),
                                ('rival', 'candidates'), ('npc', 'npcs')):
            aliases = self.config.get('entities', {}).get(kind, {})
            result[kind] = {item.id: list(dict.fromkeys([item.name, item.id] + aliases.get(item.id, [])))
                            for item in getattr(state, attribute)}
        return result

    def history(self, state):
        cutoff = state.week - self.config['history_weeks']
        return [item for item in state.world.get(HISTORY, []) if item['week'] >= cutoff]

    def profile(self, state, kind, target):
        if kind == 'group':
            group = self.systems.get_group(state, target)
            if group is None:
                raise CardError('Адресат больше не существует.')
            issues = dict(group.issues)
            for topic, source in self.config.get('issue_sources', {}).items():
                if source in issues:
                    issues[topic] = issues[source]
            return {'issues': issues, **self.config['profiles'].get(target, {})}
        return self.config['profiles'].get(target, {})

    def validate(self, state, card):
        spec = self.config['actions'].get(card.action_type)
        if spec is None:
            raise CardError('Этот тип пока не подключён к смысловому ходу. Поддержаны встреча, интервью и субботник.')
        if card.target_kind != spec['target_kind'] or card.target_id not in self.entities(state).get(card.target_kind, {}):
            raise CardError('Укажи существующего адресата: ' + spec['target_kind'] + '.')
        if not card.topic or card.topic not in self.config['topics']:
            raise CardError('Укажи известную тему действия (например: о медицине или о работе).')
        if card.legality not in ('', 'legal'):
            raise CardError('Незаконный вариант этого действия ещё не реализован; он не будет заменён безопасным.')
        if card.facts or any(key != 'money' for key in card.resources):
            raise CardError('Факты, люди и связи как ресурсы ещё не подключены к этому типу.')
        if card.event:
            hot = state.world.get('hot_groups', {}).get(card.target_id, {})
            labels = self.config['event_labels'].get(card.event, [])
            if hot.get('event') not in labels or hot.get('until', 0) < state.week:
                raise CardError('Указанное событие сейчас не происходит у этого адресата.')
        cost = max(spec['cost'], card.resources.get('money', 0))
        if not float(cost).is_integer():
            raise CardError('Сумма должна быть целым числом.')
        return spec, int(cost)

    def evaluate(self, state, card, profile=None):
        spec, cost = self.validate(state, card)
        records = self.history(state) + [{'card': qa['semantic_card']} for qa in state.week_actions if 'semantic_card' in qa]
        repetitions = sum(ActionCard.from_dict(item['card']).signature() == card.signature() for item in records)
        conflicting = any(item['card'].get('topic') == card.topic and item['card'].get('stance')
                          and card.stance and item['card']['stance'] != card.stance for item in records)
        profile = profile if profile is not None else self.profile(state, card.target_kind, card.target_id)
        context = ActionContext(available_resources={'money': state.player.money},
                                repetitions=repetitions,
                                consistency=self.config['contradiction_factor'] if conflicting else 1.0,
                                event_place_match=profile.get('places', {}).get(card.place, 1.0))
        skill = max(0, min(100, getattr(state.player, spec['skill'])))
        base = min(100, max(0, spec['base_chance'] + skill * spec['skill_weight']))
        result = evaluate_action(replace(card, confirmed=True), base, 1.0, profile, self.config['rules'], context)
        return result, cost

    def describe(self, state, card):
        result, cost = self.evaluate(state, card)
        target = next(item.name for item in getattr(state, 'groups' if card.target_kind == 'group' else 'publications') if item.id == card.target_id)
        fields = [('Действие', LABELS[card.action_type]), ('Адресат', target), ('Тема', card.topic),
                  ('Позиция', card.stance or 'не задана'), ('Канал', card.channel or 'не задан'),
                  ('Публичность', card.visibility or 'не задана'), ('Место', card.place or 'не задано'),
                  ('Событие', card.event or 'не задано'), ('Ресурсы', str(dict(card.resources))),
                  ('Цель', card.goal or 'не задана')]
        lines = ['Понял как:'] + [f'{name}: {value}' for name, value in fields]
        lines += [f'Цена: {cost}. Шанс при подтверждении: {result.chance:g}%. Множитель эффекта: {result.effect:g}.',
                  f'Творческие детали: +{result.creativity_chance:g} п.п., ×{result.creativity_effect:g} (предел +20 / ×1.5).']
        lines += [f'{REASONS[reason.source]}: шанс ×{reason.chance_factor:g}, эффект ×{reason.effect_factor:g}' for reason in result.reasons if reason.source != 'creativity']
        lines += ['Подтвердить: «подтвердить действие». Отмена: «отменить карточку».',
                  'Правка: «карточка тема jobs», «карточка адресат workers», «карточка позиция against»,',
                  '«карточка канал personal», «карточка деньги 500», «карточка цель <текст>».',
                  'Или «исправить <полная новая фраза>». Незаданные поля не додумываются.']
        return '\n'.join(lines)

    def edit(self, state, command):
        pending = state.parser_context.get(PENDING)
        if not pending:
            raise CardError('Нет карточки для правки.')
        parts = command.split(maxsplit=2)
        fields = {'тема': 'topic', 'адресат': 'target', 'позиция': 'stance', 'канал': 'channel',
                  'место': 'place', 'цель': 'goal', 'деньги': 'resources'}
        if len(parts) != 3 or parts[1] not in fields:
            raise CardError('Формат: карточка тема|адресат|позиция|канал|место|цель|деньги <значение>.')
        field = fields[parts[1]]
        card = ActionCard.from_dict(pending['card'])
        value = parts[2].strip()
        changes = {}
        if field == 'target':
            matches = [(kind, key) for kind, bucket in self.entities(state).items() for key, aliases in bucket.items()
                       if value.casefold() in [alias.casefold() for alias in aliases]]
            if len(matches) != 1:
                raise CardError('Укажи однозначного адресата по имени или id.')
            changes = dict(zip(('target_kind', 'target_id'), matches[0]))
        elif field == 'resources':
            if not value.isdigit():
                raise CardError('Деньги: целое неотрицательное число.')
            changes = {'resources': {'money': int(value)}}
        else:
            changes[field] = value
        raw = card.raw + '\n' + command
        start = len(card.raw) + 1 + command.index(parts[2])
        evidence = tuple(ev for ev in card.evidence if ev.field != field)
        changes.update(raw=raw, evidence=evidence + (Evidence(field, start, len(raw), linked=True),), confirmed=False)
        edited = replace(card, **changes)
        message = self.describe(state, edited)  # validate before replacing draft
        pending['card'] = edited.to_dict()
        pending['fingerprint'] = self.fingerprint()
        return reply(message)

    def confirm(self, state, rng, memory):
        pending = state.parser_context.get(PENDING)
        if not pending:
            return reply('Нет действия для подтверждения.')
        if pending['week'] != state.week or pending['fingerprint'] != self.fingerprint():
            state.parser_context.pop(PENDING, None)
            return reply('Контекст или словарь изменился. Введи действие заново.')
        card = replace(ActionCard.from_dict(pending['card']), confirmed=True)
        result, cost = self.evaluate(state, card)
        if cost > state.player.money:
            return reply('Недостаточно денег. Карточка оставлена для правки.')
        spec = self.config['actions'][card.action_type]
        base = copy.copy(self.systems.ACTIONS[spec['catalog_id']])
        base.cost = cost
        audience_effects = {}
        for group in state.groups:
            if card.target_kind == 'group' and group.id != card.target_id:
                continue
            if card.target_kind == 'publication' and group.id not in self.config['audiences'].get(card.target_id, []):
                continue
            audience, _ = self.evaluate(state, card, self.profile(state, 'group', group.id))
            audience_effects[group.id] = audience.effect
        ok, message = self.systems.enqueue_action(state, base, card.target_id, base.intent, False,
                                                  card.topic, {'raw': card.raw})
        if not ok:
            return reply(message)
        queued = state.week_actions[-1]
        queued.update(semantic_card=card.to_dict(), semantic_evaluation=asdict(result),
                      semantic_audience=audience_effects, chance=result.chance)
        cache = self.cache(memory)
        cache[self.phrase_key(card.raw)] = card.to_dict()
        while len(cache) > 500:
            cache.pop(next(iter(cache)))
        state.parser_context.pop(PENDING, None)
        warning = ''
        try:
            self.engine.save_memory(memory)
        except OSError:
            warning = '\nКарточка принята, но файл памяти не записан. Подтверждать повторно не нужно.'
        self.engine.save_game(state, rng)
        return reply(f'Принято после подтверждения: {LABELS[card.action_type]}. Шанс {result.chance:g}%, цена {cost}.\n'
                     + self.describe_queued(queued) + warning)

    @staticmethod
    def describe_queued(qa):
        card = qa['semantic_card']
        return f'Адресат: {card["target_id"]}; тема: {card["topic"]}; позиция: {card["stance"] or "не задана"}; цель: {card["goal"] or "не задана"}.'

    def handle(self, state, rng, command, memory):
        text = (command or '').strip()
        low = text.casefold()
        if self.review is not None:
            return reply('Сначала заверши разбор результатов недели.')
        if state.is_game_over:
            return self.old_handle(state, rng, command, memory)
        try:
            if low == 'подтвердить действие':
                return self.confirm(state, rng, memory)
            if low == 'отменить карточку':
                state.parser_context.pop(PENDING, None)
                return reply('Карточка отменена. Деньги и слот не потрачены.')
            if low.startswith('карточка '):
                return self.edit(state, text)
            if low == 'память очистить':
                state.parser_context.pop(PENDING, None)
                return self.old_handle(state, rng, command, memory)
            if low.startswith('память забыть '):
                self.cache(memory).pop(self.phrase_key(text[len('память забыть '):]), None)
                self.engine.save_memory(memory)
                return reply('Трактовка этой точной фразы забыта.')
            if low in SERVICE or low.startswith(('отзыв', 'детализация ', 'отменить ', 'отмена ', 'внеси закон ', 'закон ', 'выбор ')) or low in ('отмена', 'отменить'):
                return self.old_handle(state, rng, command, memory)
            if low.startswith('action:'):
                if low in ('action:meet_group', 'action:article', 'action:free_action'):
                    return reply('Введи действие с адресатом и темой. Например: встретиться с рабочими о работе.')
                return self.old_handle(state, rng, command, memory)
            if low.startswith('исправить '):
                text = text[len('исправить '):].strip()
            # Any new phrase replaces the old draft, even if it fails parsing.
            state.parser_context.pop(PENDING, None)
            outcome = parse_action(text, self.config['grammar'], self.entities(state), self.config['topics'])
            if outcome.status != 'parsed':
                return reply(outcome.message + ('\n' + '\n'.join(outcome.suggestions) if outcome.suggestions else ''))
            card = outcome.card
            cached = self.cache(memory).get(self.phrase_key(text))
            if cached:
                try:
                    remembered = ActionCard.from_dict(cached)
                    if remembered.raw == text:
                        card = replace(remembered, confirmed=False)
                except (CardError, TypeError, ValueError):
                    pass
            message = self.describe(state, card)
            state.parser_context[PENDING] = {'card': card.to_dict(), 'week': state.week, 'fingerprint': self.fingerprint()}
            return reply(message)
        except CardError as exc:
            return reply(str(exc))

    def effective(self, state, qa):
        action = self.old_effective(state, qa)
        if action is not None and 'semantic_card' in qa:
            action = copy.copy(action)
            action._semantic_qa = copy.deepcopy(qa)
        return action

    def resolve(self, state, action, rng):
        qa = getattr(action, '_semantic_qa', None)
        if qa is None:
            return self.old_resolve(state, action, rng)
        card = ActionCard.from_dict(qa['semantic_card'])
        evaluation = qa['semantic_evaluation']
        roll = rng.randrange(100000) / 1000
        success = roll < evaluation['chance']
        spec = self.config['actions'][card.action_type]
        effects = []
        for template in spec['success' if success else 'failure']:
            if template['type'] in ('group_mood', 'group_loyalty', 'support'):
                for group_id, factor in qa['semantic_audience'].items():
                    multiplier = factor if success else abs(factor)
                    effects.append({**template, 'group': group_id,
                                    'subject': state.player.name, 'kind': 'candidate',
                                    'delta': int(round(template['delta'] * multiplier))})
            else:
                effects.append({**template, 'delta': int(round(template['delta'] * abs(evaluation['effect'])))})
        primary = (f'{LABELS[card.action_type]}: {"успех" if success else "неудача"}; '
                   f'бросок {roll:g} < шанс {evaluation["chance"]:g}% — {"да" if success else "нет"}. '
                   + self.describe_queued(qa))
        reasons = [f'{REASONS[item["source"]]}: шанс ×{item["chance_factor"]:g}, эффект ×{item["effect_factor"]:g}' for item in evaluation['reasons']]
        script = {'primary': primary, 'secondary': reasons, 'effects': effects, 'reactors': [],
                  'tone': 0.3 if success else -0.3, 'plausibility': 1.0, 'delayed': [],
                  'tier_distribution': {}, 'tone_vector': {}, 'reason_key': 'semantic',
                  'semantic_card': card.to_dict(), 'semantic_evaluation': evaluation}
        clipping = None
        if card.visibility != 'secret':
            clipping = {'archive_no': state.next_archive_no, 'week': state.week, 'publication': card.target_id if card.target_kind == 'publication' else '',
                        'headline': LABELS[card.action_type] + ': ' + card.topic,
                        'lead': primary, 'body': '\n'.join(reasons), 'reason': primary,
                        'tone': script['tone'], 'source': 'semantic'}
            state.next_archive_no += 1
            state.clippings.append(clipping)
            state.clippings[:] = state.clippings[-40:]
            state.news_feed.append(clipping)
            state.news_feed[:] = state.news_feed[-30:]
        self.systems.add_log(state, primary)
        return True, success, primary, script, clipping

    def begin(self, state):
        if self.review is None:
            self.review = self.old_begin(state)
        return self.review

    def finish(self, state, verdicts, rng_unused=None):
        if self.review is None:
            raise RuntimeError('Сначала нужно рассчитать результаты недели.')
        records = [{'week': state.week, 'card': item['script']['semantic_card'], 'success': item.get('success', False)}
                   for item in self.review if 'semantic_card' in item['script']]
        self.old_finish(state, verdicts, rng_unused)
        state.world[HISTORY] = (state.world.get(HISTORY, []) + records)[-200:]
        self.review = None

    def clear(self, state):
        state.parser_context.pop(PENDING, None)
        return self.old_clear(state)

    def plan(self, state):
        lines = self.old_plan(state)
        for index, qa in enumerate(state.week_actions):
            if 'semantic_card' in qa:
                lines[index] = f'{index + 1}. {LABELS[qa["semantic_card"]["action_type"]]}: {self.describe_queued(qa)} (шанс ~{qa["chance"]:g}%, цена {qa["cost_paid"]})'
        return lines

    def install(self):
        if self.original:
            raise RuntimeError('Semantic runtime already installed')
        hooks = [(self.engine, 'handle_command', 'old_handle', self.handle),
                 (self.engine, '_clear_pending', 'old_clear', self.clear),
                 (self.systems, '_effective_action', 'old_effective', self.effective),
                 (self.systems, 'resolve_action', 'old_resolve', self.resolve),
                 (self.systems, 'begin_week_end', 'old_begin', self.begin),
                 (self.systems, 'finish_week', 'old_finish', self.finish),
                 (self.systems, 'plan_lines', 'old_plan', self.plan)]
        prepared = [(obj, name, alias, function, getattr(obj, name)) for obj, name, alias, function in hooks]
        for obj, name, alias, function, original in prepared:
            setattr(self, alias, original)
            self.original.append((obj, name, original))
            setattr(obj, name, function)

    def uninstall(self):
        for obj, name, original in reversed(self.original):
            setattr(obj, name, original)
        self.original.clear()
        self.review = None
