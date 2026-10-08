"""Two human candidates, one authoritative town. No UI / networking dependencies.

Two projections reuse the solo handlers, with independent trust, promises, money,
skills and threats. Shared support/policies/council are synchronized transactionally.
The opening player alternates every week. No AI moves in a PvP game.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import random
from dataclasses import asdict
from pathlib import Path

from . import engine as E
from . import press
from . import intent as I
from .session import Session, fact_line, election_chart

FORMAT = 1
LEGACY_RULES = "93cd66734f2f8312721ba210b3f355e97f26fe1af04b234be449dd45fa424821"


def fingerprint(data):
    clean = {k: v for k, v in data.items() if not k.startswith('_')}
    # Include the actual training corpus, not the transient Python classifier.
    clean['corpus'] = E.load_json(E.DATA_DIR / 'train_phrases.json')
    return hashlib.sha256(json.dumps(clean, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def candidate(name, gender, skills):
    return {'name': name, 'gender': gender, 'skills': skills}


class Match:
    def __init__(self, data, candidates, seed=None):
        if len(candidates) != 2:
            raise E.RuleError('Для P2P нужны два кандидата')
        self.data = data
        seed = seed if seed is not None else E._entropy_seed()
        self.states = [E.new_game(data, c['name'], c['skills'], c['gender'], seed + i * 104729)
                       for i, c in enumerate(candidates)]
        if any(len(s.player_name) > 64 for s in self.states):
            raise E.RuleError('Имя кандидата: максимум 64 символа')
        self.ready = [False, False]
        self.revision = 0
        self.turn = 0
        self.reports = [None, None]
        self.journal = []
        self.ended = False
        # Equal starts for human candidates; solo's incumbent advantage is not used.
        for gid, gd in data['groups'].items():
            initial = (gd['start']['support_player'] + gd['start']['support_rival']) / 2.0
            for s in self.states:
                s.groups[gid].support_player = s.groups[gid].support_rival = initial
        # Neither human starts as an incumbent with five council mandates.
        council = dict(data['council']['start'])
        human = [k for k, v in data['council']['lists'].items() if v['vote'] != 'base']
        neutral = [k for k, v in data['council']['lists'].items() if v['vote'] == 'base']
        per_human = data['council']['seats'] // 4
        for k in human:
            council[k] = per_human
        remainder = data['council']['seats'] - 2*per_human
        for n, k in enumerate(neutral):
            council[k] = remainder // len(neutral) + (n < remainder % len(neutral))
        for s in self.states:
            s.council = dict(council)
        self._sync(0)

    def scoped_data(self, player):
        d = dict(self.data)
        d['rival'] = dict(d['rival'])
        other = self.states[1-player].player_name
        d['rival']['forms'] = {k: other for k in d['rival']['forms']}
        d['rival']['title'] = 'кандидат'
        d['council'] = copy.deepcopy(d['council'])
        for lst in d['council']['lists'].values():
            original = lst['vote']
            if original in ('player', 'rival'):
                who = 0 if original == 'player' else 1
                lst['name'] = 'Блок «' + self.states[who].player_name + '»'
                lst['vote'] = 'player' if who == player else 'rival'
        # Newspapers keep their editorial templates but not an incumbent preference.
        d['papers'] = copy.deepcopy(d['papers'])
        for paper in d['papers'].values():
            paper['bias_player'] = paper['bias_rival'] = 0.0
        return d

    def session(self, player):
        s = Session(self.scoped_data(player))
        s.state = self.states[player]
        return s

    def _sync(self, actor):
        mine, other = self.states[actor], self.states[1-actor]
        other.policies = dict(mine.policies)
        other.council = dict(mine.council)
        for gid in mine.groups:
            mg, og = mine.groups[gid], other.groups[gid]
            og.support_player, og.support_rival = mg.support_rival, mg.support_player
        for i, s in enumerate(self.states):
            s.rival_positions = dict(self.states[1-i].positions)
            for gid, g in s.groups.items():
                g.rival_trust = self.states[1-i].groups[gid].trust
        # A shared adopted policy fulfills either candidate's matching promise.
        for i, s in enumerate(self.states):
            for promise in s.promises:
                if promise.status == 'open' and s.policies.get(promise.proposal) == promise.side:
                    E._keep_promise(s, self.scoped_data(i), promise)
                    # Promise reward can transfer votes; mirror without recursive checking.
                    o = self.states[1-i]
                    for gid, g in s.groups.items():
                        o.groups[gid].support_player = g.support_rival
                        o.groups[gid].support_rival = g.support_player
        for i, s in enumerate(self.states):
            E.resolve_deals(s, self.scoped_data(i))
            for gid, g in s.groups.items():
                g.rival_trust = self.states[1-i].groups[gid].trust

    def command(self, player, revision, op, payload=None):
        if type(player) is not int or player not in (0, 1):
            raise E.RuleError('Неизвестный игрок')
        if type(revision) is not int or revision != self.revision:
            raise E.RuleError('Состояние изменилось — дождитесь обновления')
        if self.ended:
            raise E.RuleError('Партия окончена: кандидат погиб')
        if player != self.turn or self.ready[player]:
            raise E.RuleError('Сейчас ход другого кандидата')
        # Reject malformed messages before touching the actual match.
        clone = copy.copy(self)
        clone.states = copy.deepcopy(self.states)
        clone.ready = list(self.ready)
        clone.journal = list(self.journal)
        clone.reports = copy.deepcopy(self.reports)
        lines = clone._command(player, op, payload)
        clone.revision += 1
        self.__dict__.update(clone.__dict__)
        return lines

    def _command(self, player, op, payload):
        if op == 'plan':
            if not isinstance(payload, dict) or set(payload) != {'text', 'cards'}:
                raise E.RuleError('Неверный формат плана')
            if not isinstance(payload['text'], str) or len(payload['text']) > self.data['intents']['max_text']:
                raise E.RuleError('Неверный текст плана')
            raws = payload['cards']
            if not isinstance(raws, list) or not 1 <= len(raws) <= self.data['intents']['max_steps']:
                raise E.RuleError('План: 1..3 операции')
            graph = I.analyze(self.scoped_data(player), payload['text'], self.states[player])
            if len(graph.steps) != len(raws):
                raise E.RuleError('Количество операций не совпадает с текстом плана')
            # The host rechecks semantic guards; the guest sends only explicitly
            # confirmed corrections, never engine effects or arbitrary predicates.
            for step, raw in zip(graph.steps, raws):
                if not isinstance(raw, dict) or set(raw) != set(asdict(E.Card('meeting'))):
                    raise E.RuleError('Неверная карточка плана')
                try:
                    card = E.Card(**raw)
                except TypeError as exc:
                    raise E.RuleError('Неверная карточка плана') from exc
                I.validate_card(self.data, card)
                card.text = step.card.text if step.card else step.text
                step.card = card
                step.ambiguities.clear()  # these are the guest's explicit choices
            I.compile_intent(self.states[player], self.scoped_data(player), graph)
            lines = []
            for index, step in enumerate(graph.steps, 1):
                if not I.condition_ok(self.states[player], step.condition):
                    raise E.RuleError('Условие шага изменилось')
                current = self._command(player, 'action', {'card': asdict(step.card), 'text': step.card.text})
                if len(graph.steps)>1:
                    lines.append('Шаг '+str(index)+'/'+str(len(graph.steps)))
                lines += current
            I.remember(self.states[player], self.scoped_data(player), graph)
            return lines
        if op == 'action':
            if not isinstance(payload, dict) or set(payload) != {'card', 'text'}:
                raise E.RuleError('Неверная команда действия')
            raw = payload['card']
            if not isinstance(raw, dict) or set(raw) != set(asdict(E.Card(action='meeting'))):
                raise E.RuleError('Неверная карточка')
            for k, v in raw.items():
                if k in ('side', 'deadline'):
                    if type(v) is not int:
                        raise E.RuleError('Позиция и срок должны быть целыми')
                elif not isinstance(v, str) or len(v) > (2000 if k == 'text' else 256):
                    raise E.RuleError('Неверный слот карточки')
            if raw['action'] not in self.data['actions'] or raw['side'] not in (-1, 0, 1):
                raise E.RuleError('Неизвестное действие или позиция')
            if not isinstance(payload['text'], str) or len(payload['text']) > 2000:
                raise E.RuleError('Фраза: максимум 2000 символов')
            sess = self.session(player)
            sess.pending = E.Card(**raw)
            sess.text = payload['text']
            lines = sess.confirm()
            self._sync(player)
            desc = E.describe_card(self.data, E.Card(**raw))
            self.journal.append(f'Неделя {sess.state.week} · {sess.state.player_name}: {desc} · {lines[0]}')
            del self.journal[:-500]
            return lines
        if op != 'ready':
            raise E.RuleError('Неизвестная сетевая команда')
        self.ready[player] = True
        if not all(self.ready):
            self.turn = 1-player
            return ['Ваши действия завершены. Ход другого кандидата.']
        self._end_week()
        return ['Неделя завершена обоими кандидатами.']

    def _end_week(self):
        week = self.states[0].week
        starts = [len(s.facts) for s in self.states]
        incomes = []
        # Personal phases apply to both candidates, in alternating order.
        for i in ((week-1) % 2, 1-(week-1) % 2):
            s, d = self.states[i], self.scoped_data(i)
            for p in s.promises:
                if p.status == 'open' and p.deadline_week <= week:
                    E._break_promise(s, d, p)
            E.resolve_deals(s, d, end=True)
            self._sync(i)
        # Drift: compute each personal result against the same shared snapshot.
        # Do not run solo's rival drift a second time.
        projected = []
        for i, s in enumerate(self.states):
            scratch = copy.deepcopy(s)
            E._drift(scratch, self.scoped_data(i))
            projected.append({gid: g.support_player for gid, g in scratch.groups.items()})
        for i, s in enumerate(self.states):
            for gid, g in s.groups.items():
                g.support_player = projected[i][gid]
                g.support_rival = projected[1-i][gid]
            avg = sum(g.support_player for g in s.groups.values()) / len(s.groups)
            income = int(round(self.data['economy']['income_base'] + self.data['economy']['income_per_support'] * avg))
            incomes.append(income)
            s.money += income
            E._threat_phase(s, self.scoped_data(i), E.week_rng(s, 1000))
            self._sync(i)
        self.ended = any(s.dead for s in self.states)
        results = [None, None]
        if not self.ended and week >= self.states[0].next_election_week:
            e = E.election(self.states[0], self.scoped_data(0), E.week_rng(self.states[0], 2000))
            reverse = copy.deepcopy(e)
            reverse['player'], reverse['rival'] = e['rival'], e['player']
            reverse['won'] = e['rival'] > e['player']
            for row in reverse['rows']:
                row['player'], row['rival'] = row['rival'], row['player']
                row['share_player'] = round(1-row['share_player'], 3)
            results = [e, reverse]
            for i, s in enumerate(self.states):
                result = results[i]
                s.elections.append(result)
                s.council = dict(e['council']['seats'])
                if result['player'] != result['rival']:
                    s.role = 'мэр' if result['won'] else 'оппозиция'
                s.next_election_week = week + self.data['meta']['election_period_weeks']
                E._fact(s, 'election', 'player', 1 if result['won'] else -1, 20,
                        extra={'pv': result['player'], 'rv': result['rival'], 'won': result['won']})
        next_seed = E._entropy_seed()
        for i, s in enumerate(self.states):
            d = self.scoped_data(i)
            articles = press.write_week(s, d, [f for f in s.facts if f.week == week], E.week_rng(s, 3000))
            lines = [f'— Итоги недели {week} · доход +{incomes[i]}']
            lines += [fact_line(d, f) for f in s.facts[starts[i]:]]
            if results[i]:
                r = results[i]
                lines.append(f'ВЫБОРЫ: {s.player_name} {r["player"]} : {r["rival"]}')
            self.reports[i] = {'week': week, 'income': incomes[i], 'articles': articles, 'lines': lines,
                               'election': results[i], 'dead': s.dead, 'match_ended': self.ended}
            if results[i]:
                self.reports[i]['chart'] = election_chart(d, s, results[i])
            s.week += 1
            s.actions_left = 0 if self.ended else (self.data['meta']['actions_per_week'] - (s.week <= s.injured_until))
            s.week_cards = []
            s.week_seeds.append(next_seed + i*104729)
            del s.week_seeds[:-200]
        common_articles = []
        for i, rep in enumerate(self.reports):
            for article in rep['articles']:
                a = dict(article)
                a['paper_name'] += ' · о кандидате ' + self.states[i].player_name
                common_articles.append(a)
        for rep in self.reports:
            rep['articles'] = copy.deepcopy(common_articles)
        self.ready = [False, False]
        self.turn = (week % 2)

    def snapshot(self):
        return {'format': FORMAT, 'rules': fingerprint(self.data), 'revision': self.revision,
                'states': [E.to_dict(s) for s in self.states], 'ready': self.ready,
                'turn': self.turn, 'reports': self.reports, 'journal': self.journal, 'ended': self.ended}

    @classmethod
    def restore(cls, data, obj):
        try:
            if obj['format'] != FORMAT or obj['rules'] not in (fingerprint(data), LEGACY_RULES):
                raise E.DataError('P2P: несовместимая версия правил / сохранения')
            if (not isinstance(obj['states'], list) or len(obj['states']) != 2
                    or type(obj['revision']) is not int or obj['revision'] < 0
                    or type(obj['turn']) is not int or obj['turn'] not in (0, 1)
                    or not isinstance(obj['ready'], list) or len(obj['ready']) != 2
                    or any(type(v) is not bool for v in obj['ready'])
                    or not isinstance(obj['reports'], list) or len(obj['reports']) != 2
                    or any(v is not None and not isinstance(v, dict) for v in obj['reports'])
                    or not isinstance(obj['journal'], list) or len(obj['journal']) > 500
                    or any(not isinstance(v, str) for v in obj['journal'])
                    or type(obj['ended']) is not bool):
                raise E.DataError('P2P: повреждённое состояние')
            m = cls.__new__(cls)
            m.data = data
            m.states = [E.from_dict(s) for s in obj['states']]
            if m.states[0].week != m.states[1].week:
                raise E.DataError('P2P: недели не совпадают')
            for state in m.states:
                if (type(state.week) is not int or state.week < 1 or set(state.groups) != set(data['groups'])
                        or set(state.policies) != set(data['proposals'])
                        or set(state.positions) != set(data['proposals'])
                        or set(state.council) != set(data['council']['lists'])
                        or sum(state.council.values()) != data['council']['seats']):
                    raise E.DataError('P2P: неверные поля города')
                for g in state.groups.values():
                    for value in (g.support_player, g.support_rival, g.trust, g.rival_trust):
                        if (isinstance(value, bool) or not isinstance(value, (int, float))
                                or not math.isfinite(value) or not 0 <= value <= 100):
                            raise E.DataError('P2P: неверные показатели группы')
            for key in ('revision', 'ready', 'turn', 'reports', 'journal', 'ended'):
                setattr(m, key, copy.deepcopy(obj[key]))
            return m
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise E.DataError('P2P: повреждённое состояние') from exc

    def save(self, path):
        obj = self.snapshot()
        raw = json.dumps(obj, sort_keys=True, ensure_ascii=False).encode('utf-8')
        envelope = {'sha256': hashlib.sha256(raw).hexdigest(), 'match': obj}
        p = Path(path)
        tmp = p.with_suffix(p.suffix + '.tmp')
        tmp.write_text(json.dumps(envelope, ensure_ascii=False, indent=1), encoding='utf-8')
        tmp.replace(p)

    @classmethod
    def load(cls, data, path):
        obj = E.load_json(Path(path))
        try:
            raw = json.dumps(obj['match'], sort_keys=True, ensure_ascii=False).encode('utf-8')
            if hashlib.sha256(raw).hexdigest() != obj['sha256']:
                raise E.DataError('P2P: контрольная сумма сохранения не совпадает')
            return cls.restore(data, obj['match'])
        except (KeyError, TypeError) as exc:
            raise E.DataError('P2P: повреждённое сохранение') from exc
