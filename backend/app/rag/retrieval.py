"""
Hybrid retrieval: BM25 keywords + vector similarity, fused with Reciprocal Rank Fusion (RRF),
optionally re-ordered by a cross-encoder.  Without a ready semantic index it is plain BM25.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.config import settings
from app.rag.bm25 import KBHit, KBIndex, pick_best
from app.core.metrics import metrics
from app.rag.semantic import embedding as sem_models
from app.rag.semantic.index import article_text, semantic_index

logger = logging.getLogger("call_center")

RRF_K = 60


@dataclass
class Candidate:
    doc_id: int
    coverage: float = 0.0          # BM25 term coverage 0..1
    matched: int = 0
    cosine: Optional[float] = None
    rerank: Optional[float] = None
    fused: float = 0.0
    lexical_ok: bool = False
    semantic_ok: bool = False

    @property
    def accepted(self) -> bool:
        return self.lexical_ok or self.semantic_ok

    @property
    def confidence(self) -> float:
        lex = self.coverage
        sem = 0.0
        if self.rerank is not None:
            sem = self.rerank
        elif self.cosine is not None:
            vmin = settings.vector_min_score  # vmin -> 0.5, 1.0 -> 1.0
            sem = (0.5 + 0.5 * (self.cosine - vmin) / (1.0 - vmin)) if self.cosine >= vmin \
                else 0.5 * max(self.cosine, 0.0) / vmin
        return max(0.0, min(1.0, max(lex, sem)))


@dataclass
class Retrieval:
    mode: str                                   # lexical | hybrid | hybrid+rerank
    candidates: List[Candidate] = field(default_factory=list)
    best: Optional[Candidate] = None            # first accepted candidate
    top: Optional[Candidate] = None             # first candidate overall (for category / confidence reporting)


def _lexical_ok(hit_matched: int, coverage: float) -> bool:
    return hit_matched >= 2 and coverage >= settings.KB_CONFIDENCE_THRESHOLD


def retrieve(index: KBIndex, articles: Dict[int, dict], query: str) -> Retrieval:
    k = settings.HYBRID_CANDIDATES
    with metrics.timed("strategy.kb"):
        lex_hits: List[KBHit] = index.search(query, k=k)
    lex = {h.doc_id: h for h in lex_hits}

    cosines: Dict[int, float] = {}
    if semantic_index.ready:
        embedder = sem_models.get_embedder()
        try:
            with metrics.timed("strategy.vector"):
                vector = embedder.embed_query(query)
                cosines = {i: s for i, s in semantic_index.store.search(vector, k) if i in articles}
        except Exception:
            logger.exception("vector search failed; using keyword search only")
            cosines = {}

    if not cosines:  # ---- keyword-only (also the fallback whenever the semantic part is off or failing)
        best_hit = pick_best(lex_hits, lambda i: articles[i]["resolution"], query)
        cands = []
        for h in lex_hits:
            cands.append(Candidate(h.doc_id, h.coverage, h.matched, lexical_ok=_lexical_ok(h.matched, h.coverage)))
        if best_hit:  # prefer same-script article among near-equal hits
            cands.sort(key=lambda c: c.doc_id != best_hit.doc_id)
        result = Retrieval("lexical", cands)
        result.top = cands[0] if cands else None
        result.best = next((c for c in cands if c.accepted), None)
        return result

    # ---- hybrid: Reciprocal Rank Fusion of the two rankings
    sem_order = sorted(cosines, key=cosines.get, reverse=True)
    cands: Dict[int, Candidate] = {}
    for rank, h in enumerate(lex_hits):
        c = cands.setdefault(h.doc_id, Candidate(h.doc_id))
        c.coverage, c.matched = h.coverage, h.matched
        c.fused += settings.HYBRID_BM25_WEIGHT / (RRF_K + rank + 1)
    for rank, doc_id in enumerate(sem_order):
        c = cands.setdefault(doc_id, Candidate(doc_id))
        c.cosine = cosines[doc_id]
        c.fused += settings.HYBRID_VECTOR_WEIGHT / (RRF_K + rank + 1)
    ordered = sorted(cands.values(), key=lambda c: c.fused, reverse=True)[:k]

    mode = "hybrid"
    if semantic_index.reranker_ready:
        reranker = sem_models.get_reranker()
        try:
            with metrics.timed("strategy.rerank"):
                docs = [(c.doc_id, article_text(articles[c.doc_id]["subject"], articles[c.doc_id]["description"],
                                                articles[c.doc_id]["resolution"], articles[c.doc_id]["product"],
                                                articles[c.doc_id]["ticket_type"])) for c in ordered]
                scores = reranker.rerank(query, docs)
            for c in ordered:
                c.rerank = scores.get(c.doc_id)
            ordered.sort(key=lambda c: (c.rerank if c.rerank is not None else -1.0, c.fused), reverse=True)
            mode = "hybrid+rerank"
        except Exception:
            logger.exception("reranking failed; keeping the fused order")

    for c in ordered:
        c.lexical_ok = _lexical_ok(c.matched, c.coverage)
        if c.rerank is not None:
            c.semantic_ok = c.rerank >= settings.RERANK_MIN_SCORE
        else:
            c.semantic_ok = c.cosine is not None and c.cosine >= settings.vector_min_score
    result = Retrieval(mode, ordered)
    result.top = ordered[0] if ordered else None
    result.best = next((c for c in ordered if c.accepted), None)
    return result
