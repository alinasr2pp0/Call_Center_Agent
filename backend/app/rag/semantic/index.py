"""Keeps the vector store in step with the knowledge base (in a background thread) and exposes its status."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Dict, Optional

from app.config import settings
from app.database import SessionLocal
from app.models import KBArticle
from app.rag.semantic import embedding as sem_models
from app.rag.semantic.vector_stores import VectorStore, build_store, text_hash

logger = logging.getLogger("call_center")


def article_text(subject: str, description: str, resolution: str, product: str, ticket_type: str) -> str:
    return " ".join(filter(None, [subject, description, resolution, product, ticket_type]))


@dataclass
class Status:
    state: str = "disabled"        # disabled | starting | ready | error
    message: str = ""
    indexed: int = 0
    reranker: str = "off"          # off | loading | ready | error


class SemanticIndex:
    def __init__(self):
        self.status = Status()
        self.store: Optional[VectorStore] = None
        self._lock = threading.Lock()
        self._dirty = False
        self._thread: Optional[threading.Thread] = None
        if settings.semantic_enabled:
            self.status = Status(state="starting", message="waiting for the first index run",
                                 reranker="loading" if settings.RERANKER_ENABLED else "off")

    # ------------------------------------------------------------------ public API
    @property
    def ready(self) -> bool:
        return self.status.state == "ready" and self.store is not None

    @property
    def reranker_ready(self) -> bool:
        return self.status.reranker == "ready"

    def request_sync(self) -> None:
        """Ask for a (re)index; coalesces bursts of KB edits into as few runs as possible."""
        if not settings.semantic_enabled:
            return
        with self._lock:
            self._dirty = True
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._worker, name="semantic-index", daemon=True)
            self._thread.start()

    def wait_idle(self, timeout: float = 60.0) -> bool:
        thread = self._thread
        if thread:
            thread.join(timeout)
            return not thread.is_alive()
        return True

    # ------------------------------------------------------------------ internals
    def _worker(self) -> None:
        while True:
            with self._lock:
                if not self._dirty:
                    return
                self._dirty = False
            try:
                self._sync_once()
            except Exception as exc:
                logger.exception("semantic index run failed")
                self.status.state, self.status.message = "error", str(exc)[:300]
            if self.status.reranker == "loading":
                self._load_reranker()

    def _sync_once(self) -> None:
        embedder = sem_models.get_embedder()
        if embedder is None:
            return
        try:
            dim = embedder.dim  # loads (and if needed downloads) the model
        except sem_models.SemanticUnavailable as exc:
            logger.warning("Semantic search disabled: %s", exc)
            self.status.state, self.status.message = "error", str(exc)
            if self.status.reranker == "loading":
                self.status.reranker = "off"
            return
        store = self.store or build_store(embedder.model_name)
        store.prepare(dim)

        with SessionLocal() as db:
            rows = db.query(KBArticle).all()
            wanted: Dict[int, tuple] = {}
            for a in rows:
                if (a.resolution or "").strip():
                    text = article_text(a.subject, a.description or "", a.resolution or "", a.product, a.ticket_type)
                    wanted[a.id] = (text, text_hash(embedder.model_name, text))
        have = store.existing()
        todo = [i for i, (_, h) in wanted.items() if have.get(i) != h]
        stale = [i for i in have if i not in wanted]
        batch = settings.EMBEDDING_BATCH_SIZE
        for start in range(0, len(todo), batch):
            chunk = todo[start:start + batch]
            vectors = embedder.embed_passages([wanted[i][0] for i in chunk])
            store.upsert([(i, v, wanted[i][1]) for i, v in zip(chunk, vectors)])
        store.delete(stale)
        self.store = store
        self.status.state = "ready"
        self.status.indexed = store.count()
        self.status.message = f"{len(todo)} embedded, {len(stale)} removed ({store.name})"
        logger.info("Semantic index ready: %s articles (%s, %s)", self.status.indexed, store.name,
                    embedder.model_name)

    def _load_reranker(self) -> None:
        reranker = sem_models.get_reranker()
        if reranker is None:
            self.status.reranker = "off"
            return
        try:
            reranker.load()
            self.status.reranker = "ready"
        except sem_models.SemanticUnavailable as exc:
            logger.warning("Reranker disabled: %s", exc)
            self.status.reranker = "error"
            self.status.message = (self.status.message + " | " + str(exc))[:300]


semantic_index = SemanticIndex()

