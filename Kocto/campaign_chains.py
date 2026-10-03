"""NPC and press story chains on top of PlayRuntime.

Data: data/world/chains.json. A chain starts from a confirmed deed (or a
scandal), then NPCs and newspapers come back to the player step by step. Each
step names who asks, what deed answers it (type/topic/recipient), a deadline
and what happens on success or failure. Only real, completed actions count;
words alone never resolve a step. Effects are applied exactly once.
"""
from __future__ import annotations

import json
from pathlib import Path

import campaign_play as play
import semantic_runtime as base

CHAINS = 'semantic_chains'
COMMANDS = {'цепочки', 'истории', 'дела'}


def load_config(path):
    config = play.load_config(path)
    extra = Path(path).with_name('chains.json')
    if extra.exists():
        config.update(json.loads(extra.read_text(encoding='utf-8')))
    return config


class ChainRuntime(play.PlayRuntime):
    @classmethod
    def from_file(cls, engine, path, allocation=None):
        return cls(engine, load_config(path), allocation)

    # --- storage ----------------------------------------------------------
    def chain_specs(self):
        return {spec['id']: spec for spec in self.config.get('chains', [])}

    def chain_state(self, state):
        data = state.world.setdefault(CHAINS, {})
        data.setdefault('active', [])
        data.setdefault('done', {})
        return data

    # --- matching ---------------------------------------------------------
    @staticmethod
    def _resolve(values, context):
        out = []
        for value in values or []:
            out.append(context.get(value[1:], value) if isinstance(value, str) and value.startswith('$') else value)
        return out

    def matches(self, rule, card, success, context=None):
        context = context or {}
        if rule.get('types') and card.get('action_type') not in rule['types']:
            return False
        topics = self._resolve(rule.get('topics'), context)
        if topics and card.get('topic') not in topics:
            return False
        targets = self._resolve(rule.get('targets'), context)
        if targets and card.get('target_id') not in targets:
            return False
        if rule.get('public') and card.get('visibility') == 'secret':
            return False
        if 'legality' in rule and (card.get('legality') or 'legal') != rule['legality']:
            return False
        if rule.get('clean') and card.get('legality') == 'illegal':
            return False
        if context.get('stance') and card.get('stance') and card['stance'] != context['stance'] and card.get('topic') == context.get('topic'):
            return False  # contradicting the original deed never counts as keeping it
        if rule.get('success', True) and not success:
            return False
        return True

    # --- effects ----------------------------------------------------------
    def apply(self, state, effects, context):
        parts = []
        for gid, delta in self._mood_items(effects.get('mood', {}), context):
            self.adjust(state, gid, delta, 0)
            name = next((g.name for g in state.groups if g.id == gid), gid)
            parts.append(f'{name} {delta:+g}')
        if effects.get('trust'):
            state.player.trust = max(0, state.player.trust + effects['trust'])
            parts.append(f'доверие {effects["trust"]:+g}')
        for name in ('evidence', 'investigation'):
            if effects.get(name) and hasattr(state.player, name):
                setattr(state.player, name, max(0, getattr(state.player, name) + effects[name]))
                parts.append(('улики ' if name == 'evidence' else 'следствие ') + f'{effects[name]:+g}')
        if effects.get('money'):
            state.player.money += effects['money']
            parts.append(f'деньги {effects["money"]:+g}')
        rivals = {item.id: item for item in getattr(state, 'candidates', [])}
        for rid, delta in (effects.get('rival') or {}).items():
            if rid in rivals:
                self.rival_popularity(rivals[rid], delta)
                parts.append(f'рейтинг {rivals[rid].name} {delta:+g}')
        if effects.get('traces') == 'bury':
            for trace in self.hidden_traces(state):
                trace['status'] = 'faded'
            parts.append('свидетель молчит — улики похоронены')
        if effects.get('traces') == 'expose' and self.hidden_traces(state):
            self.scandal(state)
            parts.append('свидетель пошёл в газету')
        return ', '.join(parts)

    @staticmethod
    def _mood_items(mood, context):
        for gid, delta in mood.items():
            yield (context.get(gid[1:], gid) if gid.startswith('$') else gid), delta

    # --- lifecycle ----------------------------------------------------------
    def start_chain(self, state, spec, context, week):
        data = self.chain_state(state)
        if any(item['id'] == spec['id'] for item in data['active']):
            return False
        done = data['done'].get(spec['id'])
        if done is not None and (not spec.get('cooldown') or week - done['week'] < spec['cooldown']):
            return False
        if len(data['active']) >= self.config.get('chains_max_active', 3):
            return False
        data['active'].append({'id': spec['id'], 'step': 0, 'due': week + spec['steps'][0].get('delay', 1),
                               'deadline': None, 'context': context, 'started': week})
        return True

    def triggers(self, state, review, week):
        for spec in self.config.get('chains', []):
            trigger = spec['trigger']
            if trigger.get('kind') != 'action':
                continue
            for item in review:
                card = item['script'].get('semantic_card')
                if card and self.matches(trigger, card, item.get('success', False)):
                    context = {'topic': card.get('topic', ''), 'target': card.get('target_id', ''), 'raw': card.get('raw', ''), 'stance': card.get('stance', '')}
                    if self.start_chain(state, spec, context, week):
                        break

    def announce(self, state, spec, item):
        step = spec['steps'][item['step']]
        item['deadline'] = state.week + step.get('deadline', 3)
        item['announced'] = True
        text = step['text'].format(**{**item['context'], 'player': state.player.name})
        ask = f' Ответ делом до недели {item["deadline"]}: {step["need"]}'
        if step.get('advice'):
            ask += f' Например: «{step["advice"]}».'
        self.publish_as(state, step.get('publication', 'independent'),
                        f'{step["who"]}: {step["headline"]}', text + ask, 'semantic_chain', step.get('tone', 0.0))

    def chain_resolve(self, state, spec, item, ok):
        data = self.chain_state(state)
        step = spec['steps'][item['step']]
        outcome = step['success' if ok else 'fail']
        summary = self.apply(state, outcome, item['context'])
        self.systems.add_log(state, f'История «{spec["title"]}», шаг {item["step"] + 1}: '
                                    f'{outcome["text"]}' + (f' ({summary})' if summary else ''))
        if outcome.get('press'):
            self.publish_as(state, outcome.get('publication', step.get('publication', 'independent')),
                            outcome['press'], outcome['text'], 'semantic_chain', 0.3 if ok else -0.4)
        last = item['step'] + 1 >= len(spec['steps'])
        if ok and not last:
            item['step'] += 1
            item['announced'] = False
            item['deadline'] = None
            item['due'] = state.week + spec['steps'][item['step']].get('delay', 1)
            return
        data['active'].remove(item)
        data['done'][spec['id']] = {'week': state.week, 'result': 'success' if ok else 'fail', 'step': item['step'] + 1}

    def chains_after(self, state, review, completed_week):
        specs = self.chain_specs()
        data = self.chain_state(state)
        for item in list(data['active']):
            spec = specs.get(item['id'])
            if spec is None:
                data['active'].remove(item)
                continue
            step = spec['steps'][item['step']]
            if item.get('announced') and 'answer' in step:
                answered = any(self.matches(step['answer'], entry['script']['semantic_card'], entry.get('success', False), item['context'])
                               for entry in review if 'semantic_card' in entry['script'])
                if answered:
                    self.chain_resolve(state, spec, item, True)
                    continue
            if item.get('announced') and state.week > item['deadline']:
                self.chain_resolve(state, spec, item, False)
        self.triggers(state, review, completed_week)
        for item in data['active']:
            spec = specs[item['id']]
            if not item.get('announced') and state.week >= item['due']:
                self.announce(state, spec, item)

    def command_answer(self, state, rng, low):
        specs = self.chain_specs()
        for item in list(self.chain_state(state)['active']):
            spec = specs.get(item['id'])
            step = spec and spec['steps'][item['step']]
            if not step or not item.get('announced') or step.get('command') != low:
                continue
            cost = step.get('command_cost', 0)
            if state.player.money < cost:
                return f'Недостаточно денег: нужно {cost}.'
            state.player.money -= cost
            self.chain_resolve(state, spec, item, True)
            self.engine.save_game(state, rng)
            return f'Сделано (−{cost}). ' + step['success']['text']
        return None

    def chains_text(self, state):
        specs = self.chain_specs()
        lines = []
        for item in self.chain_state(state)['active']:
            spec = specs.get(item['id'])
            if not spec:
                continue
            step = spec['steps'][item['step']]
            if item.get('announced'):
                hint = f' Например: «{step["advice"]}».' if step.get('advice') else ''
                lines.append(f'• «{spec["title"]}» (шаг {item["step"] + 1}/{len(spec["steps"])}): {step["who"]} ждёт до недели '
                             f'{item["deadline"]} — {step["need"]}{hint} Если нет: {step["fail"]["text"]}')
            else:
                lines.append(f'• «{spec["title"]}»: {step["who"]} объявится после недели {item["due"] - 1}.')
        done = self.chain_state(state)['done']
        finished = [f'{specs[k]["title"]} — {"успех" if v["result"] == "success" else "провал"}' for k, v in done.items() if k in specs]
        text = 'Истории (NPC и пресса помнят твои дела):\n' + ('\n'.join(lines) if lines else '• активных нет — они начинаются от твоих дел.')
        if finished:
            text += '\nЗавершены: ' + '; '.join(finished) + '.'
        return text

    # --- hooks -------------------------------------------------------------
    def scandal(self, state):
        super().scandal(state)
        spec = self.chain_specs().get(self.config.get('scandal_chain', ''))
        if spec:
            self.start_chain(state, spec, {'topic': '', 'target': '', 'raw': ''}, state.week)

    def finish(self, state, verdicts, rng_unused=None):
        review = list(self.review or [])
        week = state.week
        super().finish(state, verdicts, rng_unused)
        self.chains_after(state, review, week)

    def advisor(self, state):
        text = super().advisor(state)
        specs = self.chain_specs()
        waiting = [i for i in self.chain_state(state)['active'] if i.get('announced') and i['id'] in specs]
        if waiting:
            item = min(waiting, key=lambda i: i['deadline'])
            step = specs[item['id']]['steps'][item['step']]
            text += f'\n• {step["who"]} ждёт ответа до недели {item["deadline"]}: {step["need"]} Смотри «цепочки».'
        return text

    def handle(self, state, rng, command, memory):
        low = ' '.join((command or '').casefold().split())
        free = self.review is None and not state.is_game_over
        if free and low in COMMANDS:
            return base.reply(self.chains_text(state))
        if free:
            answer = self.command_answer(state, rng, low)
            if answer is not None:
                return base.reply(answer)
        return super().handle(state, rng, command, memory)
