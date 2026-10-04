"""ИИ понимания: стеммер + наивный байесовский классификатор + исправление опечаток.

Без внешних библиотек и без готовых весов: модель обучается при загрузке данных на
размеченных фразах из data/train_phrases.json (детерминированно, за миллисекунды).
Словарь основ в parser.py остаётся главным источником; классификатор нужен, когда
игрок пишет своими словами («заглянуть в цех к мужикам»), и чтобы выбрать одно
действие, если в фразе их несколько.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, List, Optional

WORD = re.compile(r"[а-яa-z0-9]+")
REFLEXIVE = ("ся", "сь")
ENDINGS = sorted("""иями ями ами ией ешь ете ает яет ует ишь ите ого его ому ему ыми ими ить ать ять еть уть ешь
ют ут ат ят ой ей ий ый ая яя ое ее ые ие ую юю ам ям ах ях ом ем ов ев ия ья ье ию ью ии ешь ем им
а я о е ы и у ю ь й""".split(), key=len, reverse=True)
STOP = {"и", "в", "во", "на", "с", "со", "к", "ко", "по", "о", "об", "у", "а", "что", "чтобы", "это", "мне",
        "я", "мы", "он", "она", "их", "им", "его", "её", "ее", "за", "до", "из", "от", "для", "же", "бы", "ли"}


def tokens(text: str) -> List[str]:
    return WORD.findall((text or "").lower().replace("ё", "е"))


def stem(word: str) -> str:
    w = word
    for r in REFLEXIVE:
        if w.endswith(r) and len(w) - len(r) >= 4:
            w = w[: -len(r)]
            break
    for e in ENDINGS:
        if w.endswith(e) and len(w) - len(e) >= 3:
            return w[: -len(e)]
    return w


def features(toks: List[str]) -> List[str]:
    out = []
    for t in toks:
        if t in STOP or t.isdigit():
            continue
        s = stem(t)
        out.append(s)
        if len(s) > 5:
            out.append("~" + s[:5])  # грубая основа: «обещан»/«обеща» → одно и то же
    return out


class NaiveBayes:
    def __init__(self, alpha: float = 0.5):
        self.alpha = alpha
        self.counts: Dict[str, Counter] = {}
        self.totals: Dict[str, int] = {}
        self.vocab: set = set()
        self.labels: List[str] = []

    def fit(self, samples: List[tuple]) -> "NaiveBayes":
        for text, label in samples:
            feats = features(tokens(text))
            self.counts.setdefault(label, Counter()).update(feats)
            self.vocab.update(feats)
        self.labels = sorted(self.counts)
        self.totals = {lab: sum(c.values()) for lab, c in self.counts.items()}
        return self

    def predict(self, toks: List[str]) -> Optional[Dict[str, float]]:
        feats = [f for f in features(toks) if f in self.vocab]
        if not feats:
            return None
        v = len(self.vocab)
        logp = {}
        for lab in self.labels:  # равные априорные вероятности: корпус сбалансирован вручную
            c, tot = self.counts[lab], self.totals[lab]
            logp[lab] = sum(math.log((c[f] + self.alpha) / (tot + self.alpha * v)) for f in feats)
        top = max(logp.values())
        exp = {lab: math.exp(lp - top) for lab, lp in logp.items()}
        z = sum(exp.values())
        return {lab: e / z for lab, e in exp.items()}


def levenshtein(a: str, b: str, limit: int = 2) -> int:
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return limit + 1
        prev = cur
    return prev[-1]


def fuzzy_prefix(tok: str, stem_: str) -> bool:
    """Основа ≥6 букв совпадает с началом слова с точностью до одной опечатки."""
    if len(stem_) < 6 or len(tok) < len(stem_) - 1:
        return False
    return any(levenshtein(stem_, tok[:n], 1) <= 1 for n in (len(stem_) - 1, len(stem_), len(stem_) + 1) if n <= len(tok))


def train(corpus: dict, actions: List[str]) -> NaiveBayes:
    from .engine import DataError
    phrases = corpus.get("phrases")
    if not isinstance(phrases, list) or not phrases:
        raise DataError("train_phrases.phrases: нужен непустой список")
    samples = []
    for i, p in enumerate(phrases):
        if not isinstance(p, dict) or not isinstance(p.get("text"), str) or p.get("action") not in actions:
            raise DataError("train_phrases.phrases[" + str(i) + "]: нужен text и action из " + ", ".join(actions))
        samples.append((p["text"], p["action"]))
    missing = set(actions) - {a for _, a in samples}
    if missing:
        raise DataError("train_phrases: нет примеров для " + ", ".join(sorted(missing)))
    return NaiveBayes().fit(samples)
