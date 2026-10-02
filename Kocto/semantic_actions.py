"""Semantic action foundation. Not yet enabled in the weekly game loop.

Only consumes structured, confirmed cards. It deliberately does NOT infer
syntax, world facts or intentions from keywords. No optional dependencies.
All tuning parameters must be supplied by world.json['semantic_actions'].
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

CARD_VERSION = 1
ACTION_TYPES = frozenset({
    'meeting', 'speech', 'article', 'interview', 'debate', 'canvassing',
    'leaflets', 'petition', 'fundraising', 'donation', 'volunteer_work',
    'promise', 'investigation', 'gather_rumors', 'disclosure', 'lawsuit',
    'negotiation', 'endorsement', 'criticism', 'bribe', 'blackmail',
    'disinformation', 'cover_tracks', 'appointment', 'general',
})
TARGET_KINDS = frozenset({'group', 'npc', 'rival', 'publication'})
CHANNELS = frozenset({'personal', 'newspaper', 'leaflets', 'contacts'})
FIELDS = frozenset({
    'action_type', 'target', 'topic', 'stance', 'visibility', 'channel',
    'legality', 'place', 'event', 'resources', 'goal', 'facts',
})


class CardError(ValueError):
    pass


def _number(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CardError(f'{name}: expected a number')
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise CardError(f'{name}: expected a finite number in [{low}, {high}]')
    return value


def _choice(value: str, choices: frozenset[str], name: str, optional=False):
    if not isinstance(value, str) or (value not in choices and not (optional and value == '')):
        raise CardError(f'{name}: unsupported value {value!r}')


@dataclass(frozen=True)
class Evidence:
    """A parser-verified span, not a claim automatically trusted from text.

    A future syntax parser supplies these spans AFTER establishing the relation
    to the action. Confirmation alone does not establish grammatical linkage.
    """
    field: str
    start: int
    end: int
    source: str = 'player'
    linked: bool = False


@dataclass(frozen=True)
class ActionCard:
    action_type: str
    raw: str
    target_kind: str = ''
    target_id: str = ''
    topic: str = ''
    stance: str = ''
    visibility: str = ''
    channel: str = ''
    legality: str = ''
    place: str = ''
    event: str = ''
    resources: Mapping[str, float] = field(default_factory=dict)
    goal: str = ''
    facts: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    confirmed: bool = False
    schema_version: int = CARD_VERSION

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != CARD_VERSION:
            raise CardError('unsupported card version')
        _choice(self.action_type, ACTION_TYPES, 'action_type')
        _choice(self.target_kind, TARGET_KINDS, 'target_kind', True)
        _choice(self.stance, frozenset({'for', 'against'}), 'stance', True)
        _choice(self.visibility, frozenset({'public', 'secret'}), 'visibility', True)
        _choice(self.channel, CHANNELS, 'channel', True)
        _choice(self.legality, frozenset({'legal', 'gray', 'illegal'}), 'legality', True)
        for name in ('raw', 'target_id', 'topic', 'place', 'event', 'goal'):
            if not isinstance(getattr(self, name), str):
                raise CardError(f'{name}: expected text')
        if not self.raw.strip():
            raise CardError('raw text is required')
        if bool(self.target_kind) != bool(self.target_id):
            raise CardError('target kind and id must be supplied together')
        if self.stance and not self.topic:
            raise CardError('a stance needs a topic')
        if type(self.confirmed) is not bool:
            raise CardError('confirmed must be a boolean')
        if not isinstance(self.resources, Mapping):
            raise CardError('resources must be a mapping')
        # Own copies: later changes to caller data must not alter this card.
        object.__setattr__(self, 'resources', dict(self.resources))
        for key, value in self.resources.items():
            if key not in ('money', 'people', 'connections'):
                raise CardError(f'unknown resource: {key}')
            _number(value, f'resources.{key}', 0, 1e12)
        if not isinstance(self.facts, (list, tuple)) or not all(isinstance(f, str) and f for f in self.facts):
            raise CardError('facts must be a sequence of nonempty ids')
        object.__setattr__(self, 'facts', tuple(dict.fromkeys(self.facts)))
        object.__setattr__(self, 'evidence', tuple(self.evidence))
        for ev in self.evidence:
            if not isinstance(ev, Evidence) or ev.field not in FIELDS:
                raise CardError('unknown evidence field')
            if type(ev.start) is not int or type(ev.end) is not int or not 0 <= ev.start < ev.end <= len(self.raw):
                raise CardError('evidence span is outside raw text')
            if ev.source not in ('player', 'assistant') or type(ev.linked) is not bool:
                raise CardError('invalid evidence provenance')

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ActionCard:
        if not isinstance(value, Mapping):
            raise CardError('card must be an object')
        data = copy.deepcopy(dict(value))
        try:
            data['evidence'] = tuple(Evidence(**ev) for ev in data.get('evidence', []))
            facts = data.get('facts', [])
            if not isinstance(facts, (list, tuple)):
                raise CardError('facts must be an array of ids')
            data['facts'] = tuple(facts)
            return cls(**data)
        except (TypeError, KeyError) as exc:
            raise CardError(f'invalid card: {exc}') from exc

    def present(self, name: str) -> bool:
        if name == 'target':
            return bool(self.target_id)
        return bool(getattr(self, name))

    def authored_fields(self) -> frozenset[str]:
        if not self.confirmed:
            return frozenset()
        return frozenset(ev.field for ev in self.evidence
                         if ev.linked and ev.source == 'player' and self.present(ev.field))

    def signature(self) -> str:
        # Wording/spans/confirmation do not create novelty; content does.
        data = self.to_dict()
        for key in ('raw', 'evidence', 'confirmed', 'schema_version'):
            data.pop(key)
        data['facts'] = sorted(data['facts'])
        return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class ActionContext:
    """Resolved world context. Facts/events/allies come from game state, not text."""
    known_facts: frozenset[str] = frozenset()
    available_resources: Mapping[str, float] = field(default_factory=dict)
    event_place_match: float = 1.0
    method_goal_match: float = 1.0
    consistency: float = 1.0
    repetitions: int = 0
    has_linked_chain: bool = False


@dataclass(frozen=True)
class Reason:
    source: str
    chance_factor: float
    effect_factor: float
    details: str


@dataclass(frozen=True)
class Evaluation:
    chance: float
    effect: float
    creativity_chance: float
    creativity_effect: float
    reasons: tuple[Reason, ...]


def evaluate_action(card: ActionCard, base_chance: float, base_effect: float,
                    profile: Mapping[str, Any], rules: Mapping[str, Any],
                    context: ActionContext) -> Evaluation:
    """Pure preview/result calculation. Never rolls dice or mutates game state.

    profile contains issues (0..100), channels (0..2) and positions
    ('for'/'against'). Opposition may reverse effect, not success probability.
    Unknown fields use neutral factors, rather than invented world knowledge.
    """
    if not card.confirmed:
        raise CardError('confirm interpretation before evaluation')
    chance = _number(base_chance, 'base_chance', 0, 100)
    effect = _number(base_effect, 'base_effect', -1e9, 1e9)
    def tune(key, low=0, high=10):
        if key not in rules:
            raise CardError(f'missing semantic rule: {key}')
        return _number(rules[key], key, low, high)

    min_chance = tune('min_chance', 0, 100)
    max_chance = tune('max_chance', min_chance, 100)
    topic_low = tune('topic_low')
    topic_high = tune('topic_high', topic_low)
    repeat_decay = tune('repeat_decay', 0, 1)
    max_bonus = tune('max_creativity_chance', 0, 20)
    max_mult = tune('max_creativity_effect', 1, 1.5)
    field_bonus = tune('field_bonus', 0, 20)
    fact_bonus = tune('fact_bonus', 0, 20)
    chain_bonus = tune('chain_bonus', 0, 20)
    novelty_bonus = tune('novelty_bonus', 0, 20)
    fit_bonus = tune('fit_bonus', 0, 20)

    issues = profile.get('issues', {})
    topic = 1.0
    importance = None
    if card.topic and card.topic in issues:
        importance = _number(issues[card.topic], 'topic importance', 0, 100)
        topic = topic_low + (topic_high - topic_low) * importance / 100
    position = profile.get('positions', {}).get(card.topic, '')
    if position:
        _choice(position, frozenset({'for', 'against'}), 'profile position')
    sign = -1.0 if card.stance and position and card.stance != position else 1.0
    channels = profile.get('channels', {})
    channel = _number(channels.get(card.channel, 1.0), 'channel fit', 0, 2)
    place = _number(context.event_place_match, 'event/place fit', 0, 2)
    method = _number(context.method_goal_match, 'method/goal fit', 0, 2)
    consistency = _number(context.consistency, 'consistency', 0, 2)
    if type(context.repetitions) is not int or context.repetitions < 0:
        raise CardError('repetitions must be a nonnegative integer')
    resources = 1.0
    for resource, requested in card.resources.items():
        available = _number(context.available_resources.get(resource, 0), 'available ' + resource, 0, 1e12)
        if requested:
            resources = min(resources, available / requested)
    repeat = repeat_decay ** context.repetitions
    reasons = [
        Reason('topic_target', topic, topic * sign, f'topic={card.topic or "unspecified"}; importance={importance}; position={position}'),
        Reason('channel_target', channel, channel, card.channel or 'unspecified'),
        Reason('place_time', place, place, f'place={card.place}; event={card.event}'),
        Reason('method_goal', method, method, card.goal or 'unspecified'),
        Reason('resources_scale', resources, resources, str(dict(card.resources))),
        Reason('consistency', consistency, consistency, 'resolved against campaign history'),
        Reason('repetition', repeat, repeat, f'previous uses={context.repetitions}'),
    ]
    authored = card.authored_fields()
    # Explicit syntax-linked slots only. No raw-length, word-count or tag bonus.
    specific = len(authored - {'facts', 'action_type'})
    verified_facts = set(card.facts) & set(context.known_facts) if 'facts' in authored else set()
    score = specific * field_bonus + len(verified_facts) * fact_bonus
    if authored and context.has_linked_chain:
        score += chain_bonus
    if authored and context.repetitions == 0:
        score += novelty_bonus
    if 'topic' in authored and importance is not None and importance >= 50:
        score += fit_bonus
    bonus = min(max_bonus, score)
    multiplier = 1 + (max_mult - 1) * bonus / max_bonus if max_bonus else 1.0
    reasons.append(Reason('creativity', 1.0, multiplier, f'linked authored fields={sorted(authored)}; known facts={sorted(verified_facts)}; chance bonus={bonus}'))
    for reason in reasons:
        chance *= reason.chance_factor
        effect *= reason.effect_factor
    # Zero-reach, impossible resources or method stays impossible, even with
    # creativity. A lower display bound must never rescue impossible actions.
    possible = all(r.chance_factor > 0 for r in reasons)
    chance = min(max_chance, max(min_chance, chance + bonus)) if possible else 0.0
    return Evaluation(round(chance, 3), round(effect, 3), bonus, multiplier, tuple(reasons))


class ConfirmedCardMemory:
    """In-memory exact phrase cache scoped to a dictionary fingerprint.

    No automatic learning from enqueue success; no persistence or migration of
    old tag memory here. Call remember only after the player confirms a card.
    """
    def __init__(self, dictionary_fingerprint: str):
        if not dictionary_fingerprint:
            raise CardError('dictionary fingerprint is required')
        self.fingerprint = dictionary_fingerprint
        self._cards: dict[str, dict[str, Any]] = {}

    @staticmethod
    def key(text: str) -> str:
        # Keep negation and prepositions. Do not apply old stopword stripping.
        return ' '.join(text.casefold().split())

    def remember(self, card: ActionCard):
        if not card.confirmed:
            raise CardError('unconfirmed interpretations must not be remembered')
        self._cards[self.key(card.raw)] = card.to_dict()
        while len(self._cards) > 500:
            del self._cards[next(iter(self._cards))]

    def recall(self, text: str) -> ActionCard | None:
        value = self._cards.get(self.key(text))
        return ActionCard.from_dict(value) if value is not None else None

    def forget(self, text: str):
        self._cards.pop(self.key(text), None)

    def use_dictionary(self, fingerprint: str):
        if not fingerprint:
            raise CardError('dictionary fingerprint is required')
        if fingerprint != self.fingerprint:
            self._cards.clear()
            self.fingerprint = fingerprint
