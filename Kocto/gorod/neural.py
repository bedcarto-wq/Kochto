"""Small offline MLP intent classifier, pure stdlib. No text generation or network.

Sparse word/stem/character features -> tanh hidden layer -> softmax actions.
Weights are trained offline on split=train, not every time the game starts.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import random
from collections import Counter
from . import nlu

SCHEMA = 1


def samples(corpus, actions):
    # Keep the corpus validation identical to the historical baseline.
    nlu.train(corpus, actions)
    return [(p['text'], p['action']) for p in corpus['phrases'] if p['split'] == 'train']


def digest(rows):
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def features(toks):
    out = Counter()
    words = [w for w in toks if w not in nlu.STOP and not w.isdigit()]
    for w in words:
        out['w:'+w] += 2
        out['s:'+nlu.stem(w)] += 2
        bounded = '^'+w+'$'
        for size in (3, 4):
            for i in range(len(bounded)-size+1):
                out['c:'+bounded[i:i+size]] += 0.12
    for a, b in zip(words, words[1:]):
        out['b:'+nlu.stem(a)+' '+nlu.stem(b)] += 0.5
    return out


class NeuralClassifier:
    def __init__(self, vocab, labels, hidden=24, seed=751):
        self.vocab = list(vocab)
        self.index = {f: i for i, f in enumerate(vocab)}
        self.labels = list(labels)
        self.hidden = hidden
        rng = random.Random(seed)
        self.w1 = [[rng.uniform(-0.12, 0.12) for _ in vocab] for _ in range(hidden)]
        self.b1 = [0.0]*hidden
        self.w2 = [[rng.uniform(-0.12, 0.12) for _ in range(hidden)] for _ in labels]
        self.b2 = [0.0]*len(labels)
        self.train_digest = ''
        self.loss = []

    def vector(self, toks):
        feats = features(toks)
        x = [(self.index[f], min(float(v), 2.0)) for f, v in feats.items() if f in self.index]
        norm = math.sqrt(sum(v*v for _, v in x))
        return [(i, v/norm) for i, v in x] if norm else []

    def forward(self, x):
        h = [math.tanh(b+sum(row[i]*v for i, v in x)) for b, row in zip(self.b1, self.w1)]
        scores = [b+sum(w*v for w, v in zip(row, h)) for b, row in zip(self.b2, self.w2)]
        peak = max(scores)
        probs = [math.exp(s-peak) for s in scores]
        total = sum(probs)
        return h, [p/total for p in probs]

    def supported(self, toks):
        words = [w for w in toks if w not in nlu.STOP and not w.isdigit()]
        known = sum('w:'+w in self.index or 's:'+nlu.stem(w) in self.index for w in words)
        return bool(words) and known / len(words) >= 0.40

    def predict(self, toks):
        x = self.vector(toks)
        # No prediction from a learned bias with no input evidence.
        if not x:
            return None
        return dict(zip(self.labels, self.forward(x)[1]))

    def update(self, x, label, rate):
        h, probs = self.forward(x)
        target = self.labels.index(label)
        dy = [p-(i == target) for i, p in enumerate(probs)]
        dh = [(1-v*v)*sum(self.w2[k][j]*dy[k] for k in range(len(self.labels))) for j, v in enumerate(h)]
        for k, row in enumerate(self.w2):
            self.b2[k] -= rate*dy[k]
            for j, v in enumerate(h):
                row[j] -= rate*dy[k]*v
        for j, row in enumerate(self.w1):
            self.b1[j] -= rate*dh[j]
            for i, v in x:
                row[i] -= rate*dh[j]*v
        return -math.log(max(probs[target], 1e-12))

    def extended(self, rows, weight):
        # Only the campaign copy learns; packaged weights never change.
        model = copy.deepcopy(self)
        # Replay a bounded balanced subset prevents losing all previous actions.
        replay = getattr(self, 'replay', [])
        examples = [(model.vector(nlu.tokens(t)), a) for t, a in rows if a in self.labels]
        base = [(model.vector(nlu.tokens(t)), a) for t, a in replay]
        for _ in range(3):
            for x, a in base:
                if x: model.update(x, a, 0.035)
            for _ in range(max(1, min(int(weight), 3))):
                for x, a in examples:
                    if x: model.update(x, a, 0.10)
        return model

    def record(self):
        return {'schema': SCHEMA, 'architecture': 'sparse-tanh-softmax', 'hidden': self.hidden,
                'vocab': self.vocab, 'labels': self.labels, 'train_digest': self.train_digest,
                'w1': self.w1, 'b1': self.b1, 'w2': self.w2, 'b2': self.b2}


def train(rows, hidden=24, epochs=100, seed=751, vocab_limit=2048):
    counts = Counter()
    for text, _ in rows:
        counts.update(features(nlu.tokens(text)).keys())
    # Vocabulary never sees held-out examples. Stable tie breaking.
    ranked = sorted(counts, key=lambda f: (0 if f.startswith(('s:', 'w:')) else 1, -counts[f], f))
    vocab = sorted(ranked[:vocab_limit])
    model = NeuralClassifier(vocab, sorted({a for _, a in rows}), hidden, seed)
    model.train_digest = digest(rows)
    encoded = [(model.vector(nlu.tokens(t)), a) for t, a in rows]
    counts = Counter(a for _, a in rows)
    rng = random.Random(seed)
    for epoch in range(epochs):
        order = list(encoded)
        rng.shuffle(order)
        loss = 0.0
        for x, a in order:
            # Balance rare negotiation classes without touching test data.
            rate = (0.12/(1+epoch/80))*math.sqrt(max(counts.values())/counts[a])
            loss += model.update(x, a, rate)
        model.loss.append(loss/len(rows))
    return model


def load(record, corpus, actions):
    from .engine import DataError
    try:
        rows = samples(corpus, actions)
        if not isinstance(record, dict) or record['schema'] != SCHEMA or record['architecture'] != 'sparse-tanh-softmax':
            raise ValueError('неизвестная архитектура')
        vocab, labels, hidden = record['vocab'], record['labels'], record['hidden']
        if type(hidden) is not int or not 4 <= hidden <= 64:
            raise ValueError('размер скрытого слоя')
        if not isinstance(vocab, list) or not 1 <= len(vocab) <= 2048 or any(not isinstance(v,str) or not v for v in vocab) or len(set(vocab)) != len(vocab):
            raise ValueError('словарь')
        if labels != sorted(actions): raise ValueError('набор операций не совпадает')
        if record['train_digest'] != digest(rows): raise ValueError('корпус изменён: переобучите модель')
        model = NeuralClassifier(vocab, labels, hidden)
        for key, outer, inner in (('w1', hidden, len(vocab)), ('w2', len(labels), hidden)):
            matrix = record[key]
            if not isinstance(matrix,list) or len(matrix) != outer: raise ValueError(key)
            if any(not isinstance(r,list) or len(r) != inner for r in matrix): raise ValueError(key+' dimensions')
            if any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>100 for r in matrix for v in r): raise ValueError(key+' finite values')
            setattr(model,key,matrix)
        for key, length in (('b1', hidden), ('b2', len(labels))):
            vals = record[key]
            if not isinstance(vals,list) or len(vals) != length or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>100 for v in vals): raise ValueError(key)
            setattr(model,key,vals)
        model.train_digest = record['train_digest']
        model.replay = [row for label in labels for row in [r for r in rows if r[1]==label][:4]]
        return model
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        raise DataError('neural_model: '+str(exc)) from exc
