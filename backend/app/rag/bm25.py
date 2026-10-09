"""Knowledge-base retrieval using BM25 ranking and IDF-weighted query coverage to provide interpretable relevance confidence, penalizing unmatched terms and reducing false matches on unrelated queries."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional

from app.rag.text import has_arabic, tokenize


@dataclass(frozen=True)
class KBDoc:
    id: int
    text: str
    has_resolution: bool


@dataclass(frozen=True)
class KBHit:
    doc_id: int
    score: float
    coverage: float
    matched: int = 0  # how many distinct query terms the document contains


class KBIndex:
    K1 = 1.5
    B = 0.75

    def __init__(self, docs: Iterable[KBDoc]):
        self._docs: List[KBDoc] = list(docs)
        self._tf: List[Counter] = []
        self._len: List[int] = []
        self._df: Counter = Counter()
        for doc in self._docs:
            tokens = tokenize(doc.text)
            counts = Counter(tokens)
            self._tf.append(counts)
            self._len.append(len(tokens))
            for term in counts:
                self._df[term] += 1
        self._n = len(self._docs)
        self._avg_len = (sum(self._len) / self._n) if self._n else 0.0

    def __len__(self) -> int:
        return self._n

    def _idf(self, term: str) -> float:
        df = self._df.get(term, 0)
        return math.log(1.0 + (self._n - df + 0.5) / (df + 0.5))

    def search(self, query: str, k: int = 3, require_resolution: bool = True) -> List[KBHit]:
        if not self._n:
            return []
        terms = list(dict.fromkeys(tokenize(query)))  # unique, order kept
        if not terms:
            return []
        idf: Dict[str, float] = {t: self._idf(t) for t in terms}
        total_idf = sum(idf.values()) or 1.0
        hits: List[KBHit] = []
        for i, doc in enumerate(self._docs):
            if require_resolution and not doc.has_resolution:
                continue
            tf = self._tf[i]
            score = 0.0
            matched = 0.0
            matched_terms = 0
            for term in terms:
                freq = tf.get(term, 0)
                if not freq:
                    continue
                matched += idf[term]
                matched_terms += 1
                denom = freq + self.K1 * (1 - self.B + self.B * self._len[i] / (self._avg_len or 1.0))
                score += idf[term] * (freq * (self.K1 + 1)) / denom
            if score > 0:
                hits.append(KBHit(doc.id, score, min(1.0, matched / total_idf), matched_terms))
        hits.sort(key=lambda h: (h.score, h.coverage), reverse=True)
        return hits[:k]


def meaningful_term_count(text: str) -> int:
    return len(set(tokenize(text)))


def pick_best(hits: List[KBHit], text_of: Callable[[int], str], query: str) -> Optional[KBHit]:
    """Among near-equal top hits prefer the one written in the same script as the question
    (an Arabic question should not be answered with an English article when an Arabic one fits)."""
    if not hits:
        return None
    top = hits[0]
    wants_arabic = has_arabic(query)
    for hit in hits:
        if hit.coverage < top.coverage * 0.9:
            break
        if has_arabic(text_of(hit.doc_id)) == wants_arabic:
            return hit
    return top
