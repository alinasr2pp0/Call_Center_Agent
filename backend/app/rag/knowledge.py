"""RAG retrieval entry point, orchestrating cached keyword indexing, hybrid search, result fusion, and reranking behind a unified Agent-facing API, with automatic cache invalidation on knowledge-base changes."""

from __future__ import annotations

import threading
from typing import Dict, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import KBArticle
from app.rag import retrieval
from app.rag.bm25 import KBDoc, KBIndex

_cache_lock = threading.Lock()
_cache: dict = {"signature": None, "index": None, "articles": {}}


def load_index(db: Session) -> Tuple[KBIndex, Dict[int, dict]]:
    signature = db.query(func.count(KBArticle.id), func.max(KBArticle.updated_at)).one()
    signature = (signature[0], str(signature[1]))
    with _cache_lock:
        if _cache["signature"] == signature and _cache["index"] is not None:
            return _cache["index"], _cache["articles"]
        rows = db.query(KBArticle).all()
        docs = [
            KBDoc(
                id=a.id,
                text=" ".join(filter(None, [a.subject, a.description, a.resolution, a.product, a.ticket_type])),
                has_resolution=bool((a.resolution or "").strip()),
            )
            for a in rows
        ]
        index = KBIndex(docs)
        articles = {a.id: {"subject": a.subject, "product": a.product, "ticket_type": a.ticket_type,
                           "description": a.description or "", "resolution": (a.resolution or "").strip()}
                    for a in rows}
        _cache.update(signature=signature, index=index, articles=articles)
        return index, articles


def reset_cache() -> None:
    with _cache_lock:
        _cache.update(signature=None, index=None, articles={})


def search(db: Session, query: str) -> Tuple[retrieval.Retrieval, Dict[int, dict]]:
    """Retrieve candidates for ``query``; returns the retrieval result and the article texts by id."""
    index, articles = load_index(db)
    return retrieval.retrieve(index, articles, query), articles
