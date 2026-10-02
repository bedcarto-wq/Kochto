"""Conservative Russian frame parser for ActionCard.

This is a first, explicit grammar, NOT a general NLP/LLM parser. Unsupported
phrasing and ambiguous targets ask for clarification instead of being guessed.
Lexical frames and world aliases are supplied by the caller, not global files.
The existing game's language.py has not yet been switched to this parser.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from semantic_actions import ActionCard, CardError, Evidence


@dataclass(frozen=True)
class ParseOutcome:
    status: str
    card: ActionCard | None = None
    message: str = ''
    suggestions: tuple[str, ...] = ()


def _literal_pattern(alias: str) -> str:
    if not isinstance(alias, str) or not alias.strip():
        raise CardError('parser aliases must be nonempty text')
    # Unicode boundaries, literal aliases only: config cannot inject regex.
    return r'(?<!\w)' + re.escape(alias.strip().lower().replace('ё', 'е')).replace(r'\ ', r'\s+') + r'(?!\w)'


def _hits(raw: str, aliases):
    if isinstance(aliases, str) or not isinstance(aliases, (list, tuple)):
        raise CardError('aliases must be an array')
    found = []
    for alias in aliases:
        found.extend(re.finditer(_literal_pattern(alias), raw, re.IGNORECASE))
    return sorted(found, key=lambda m: (m.start(), -len(m.group())))


def _best(raw: str, aliases):
    found = _hits(raw, aliases)
    return found[0] if found else None


def parse_action(raw: str, grammar: Mapping[str, Any],
                 entities: Mapping[str, Mapping[str, list[str]]],
                 topics: Mapping[str, list[str]]) -> ParseOutcome:
    """Parse one supported clause without dropping negation or prepositions.

    grammar.frames contains type, starts and target_prepositions. Compound
    clauses are allowed ONLY through each frame's explicit continuations.
    A topic must follow a topic preposition or a recognized continuation.
    Future multi-action splitting is separate from this one-card contract.
    """
    if not isinstance(raw, str) or not raw.strip():
        return ParseOutcome('unsupported', message='Напиши, что ты хочешь сделать.')
    if len(raw) > 4000:
        return ParseOutcome('unsupported', message='Слишком длинное действие. Раздели план на отдельные ходы.')
    # Same-length character normalization keeps all Evidence offsets valid.
    text = raw.lower().replace('ё', 'е')
    frames = grammar.get('frames', [])
    if not isinstance(frames, list) or not frames:
        raise CardError('parser frames are required')
    suggested = tuple(grammar.get('suggestions', [])[:3])
    # Recognize action type at the start, not from scattered noun tags.
    # Prefixes have an explicit whitelist; arbitrary lead-in prose is not guessed.
    prefixes = grammar.get('prefixes', [])
    candidates = []
    for frame in frames:
        for match in _hits(text, frame['starts']):
            prefix = text[:match.start()].strip()
            prefix_parts = re.findall(r'[\w-]+', prefix)
            allowed = {str(x).lower().replace('ё', 'е') for x in prefixes}
            refusal = {'не', 'буду', 'отказываюсь'}
            if all(part in allowed | refusal for part in prefix_parts):
                candidates.append((match, frame, prefix_parts))
    if not candidates:
        return ParseOutcome('unsupported', message='Не распознал политическое действие. Укажи действие, адресата и тему.', suggestions=suggested)
    # Longest literal frame wins for overlapping phrases, not first dictionary hit.
    candidates.sort(key=lambda item: (item[0].start(), -len(item[0].group())))
    verb, frame, prefix_parts = candidates[0]
    best_types = {f['type'] for m, f, _ in candidates
                  if m.start() == verb.start() and len(m.group()) == len(verb.group())}
    if len(best_types) > 1:
        return ParseOutcome('needs_choice', message='Уточни тип действия.', suggestions=suggested)
    if any(part in {'не', 'отказываюсь'} for part in prefix_parts):
        return ParseOutcome('cancelled', message='Действие отменено: оно отрицается в твоей фразе.')
    evidence = [Evidence('action_type', verb.start(), verb.end(), linked=True)]
    values: dict[str, Any] = {'action_type': frame['type'], 'raw': raw}
    tail_start = verb.end()
    body = text[tail_start:]
    # Local negation scopes need a richer grammar. Never silently discard
    # an inner 'не' or invert the wrong topic/secondary action.
    if re.search(r'(?<!\w)не(?!\w)', body):
        return ParseOutcome('needs_choice', message='Уточни, какая часть действия отрицается.')

    # There must be an explicit allowed continuation for coordinated clauses.
    # '... и подкупить ...' must not quietly become part of a meeting.
    continuation_matches = _hits(text, frame.get('continuations', []))
    for conjunction in re.finditer(r'(?<!\w)(?:и|затем|потом)(?!\w)', body):
        after = tail_start + conjunction.end()
        rest = text[after:].lstrip()
        recognized = any(m.start() >= after and not text[after:m.start()].strip()
                         for m in continuation_matches)
        # Target lists ('рабочими и учителями') are handled as ambiguity below;
        # any second recognized action frame otherwise needs a separate card.
        second_action = any(_best(rest, f['starts']) and
                            _best(rest, f['starts']).start() == 0 for f in frames)
        if second_action and not recognized:
            return ParseOutcome('needs_choice', message='Здесь несколько действий. Введи их по отдельности.')

    targets = []
    for kind, bucket in entities.items():
        for target_id, aliases in bucket.items():
            for hit in _hits(text, aliases):
                if hit.start() < tail_start:
                    continue
                preceding = text[tail_start:hit.start()].strip()
                prep = next((p for p in frame.get('target_prepositions', [])
                             if preceding == p), None)
                if prep is not None or (not preceding and frame.get('direct_target', False)):
                    targets.append((kind, target_id, hit))
                # A coordinated second target is ambiguous, not silently lost.
                elif targets and re.search(r'\bи\s*$', preceding):
                    targets.append((kind, target_id, hit))
    target_ids = {(kind, target_id) for kind, target_id, _ in targets}
    if len(target_ids) > 1:
        return ParseOutcome('needs_choice', message='Укажи одного адресата для этого действия.')
    if targets:
        kind, target_id, hit = sorted(targets, key=lambda t: -len(t[2].group()))[0]
        values.update(target_kind=kind, target_id=target_id)
        evidence.append(Evidence('target', hit.start(), hit.end(), linked=True))
    elif frame.get('requires_target', False):
        return ParseOutcome('needs_choice', message='Кому адресовано действие?')

    topic_hits = []
    for topic_id, aliases in topics.items():
        for hit in _hits(text, aliases):
            if hit.start() < tail_start:
                continue
            before = text[tail_start:hit.start()]
            governed = any(re.search(_literal_pattern(p) + r'\s*$', before)
                           for p in grammar.get('topic_prepositions', ['о', 'об', 'про']))
            governed = governed or any(m.end() <= hit.start() and
                                       not text[m.end():hit.start()].strip()
                                       for m in continuation_matches)
            if governed:
                topic_hits.append((topic_id, hit))
    if len({topic_id for topic_id, _ in topic_hits}) > 1:
        return ParseOutcome('needs_choice', message='Уточни основную тему действия.')
    if topic_hits:
        topic_id, hit = sorted(topic_hits, key=lambda t: -len(t[1].group()))[0]
        values['topic'] = topic_id
        evidence.append(Evidence('topic', hit.start(), hit.end(), linked=True))
        # Stance markers must immediately govern the topic; 'против' isn't
        # refusal to carry out the action, unlike 'не встретиться'.
        before = text[tail_start:hit.start()]
        for stance, marker in (('for', 'за'), ('against', 'против')):
            marker_hit = re.search(_literal_pattern(marker) + r'\s*$', before)
            if marker_hit:
                values['stance'] = stance
                evidence.append(Evidence('stance', tail_start + marker_hit.start(), tail_start + marker_hit.end(), linked=True))

    for slot in ('visibility', 'channel', 'legality', 'place', 'event'):
        found = []
        for value, aliases in grammar.get(slot, {}).items():
            for hit in _hits(text, aliases):
                if slot in ('place', 'event'):
                    before = text[tail_start:hit.start()]
                    if hit.start() < tail_start or not re.search(r'\b(?:у|на|в|во|во время)\s*$', before):
                        continue
                elif slot == 'channel':
                    before = text[:hit.start()]
                    if not re.search(r'\b(?:через|лично|в)\s*$', before) and hit.group() != 'лично':
                        continue
                elif slot == 'visibility':
                    if hit.start() > verb.start():
                        continue
                elif slot == 'legality':
                    if hit.start() > verb.start():
                        continue
                found.append((value, hit))
        if len({value for value, _ in found}) > 1:
            return ParseOutcome('needs_choice', message=f'Уточни поле «{slot}».')
        if found:
            value, hit = found[0]
            values[slot] = value
            evidence.append(Evidence(slot, hit.start(), hit.end(), linked=True))

    goal = re.search(r'\bчтобы\s+(.+?)[.!?]*$', text)
    if goal:
        values['goal'] = raw[goal.start(1):goal.end(1)].strip()
        evidence.append(Evidence('goal', goal.start(1), goal.end(1), linked=True))
    # Explicit allocation only; do not treat arbitrary numbers/dates as money.
    amounts = list(re.finditer(r'\b(?:потратить|выделить|на сумму)\s+(\d+)\s*(?:рублей|рубля|рубль|руб|₽)(?!\w)', text))
    if len(amounts) > 1:
        return ParseOutcome('needs_choice', message='Уточни общую сумму ресурсов для действия.')
    if amounts:
        hit = amounts[0]
        values['resources'] = {'money': int(hit.group(1))}
        evidence.append(Evidence('resources', hit.start(), hit.end(), linked=True))
    values['evidence'] = tuple(evidence)
    # Never confirms for the player and never learns an interpretation here.
    return ParseOutcome('parsed', card=ActionCard(**values), message='Проверь карточку «Понял как…» и подтверди действие.')
