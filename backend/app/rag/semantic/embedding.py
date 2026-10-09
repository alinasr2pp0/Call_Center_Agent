"""Optional semantic embedding and cross-encoder reranking via sentence-transformers, loaded lazily with graceful degradation to BM25-only retrieval when dependencies or models are unavailable."""

from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional, Sequence, Tuple

from app.config import settings

logger = logging.getLogger("call_center")


class SemanticUnavailable(RuntimeError):
    """The optional AI libraries/models could not be loaded."""


class Embedder:
    """Wraps a sentence-transformers model. e5 models need the 'query: ' / 'passage: ' prefixes."""

    def __init__(self, model_name: str, device: str = "cpu", batch_size: int = 16):
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self._model = None
        self._lock = threading.Lock()
        low = model_name.lower()
        self._query_prefix = "query: " if "e5" in low else ""
        self._passage_prefix = "passage: " if "e5" in low else ""

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            try:
                from sentence_transformers import SentenceTransformer  # heavy import, done lazily
            except ImportError as exc:
                raise SemanticUnavailable(
                    "sentence-transformers is not installed (pip install -r backend/requirements-ai.txt)") from exc
            try:
                self._model = SentenceTransformer(self.model_name, device=self.device)
            except Exception as exc:  # download/offline/corrupt model
                raise SemanticUnavailable(f"could not load embedding model '{self.model_name}': {exc}") from exc

    @property
    def dim(self) -> int:
        self.load()
        return int(self._model.get_sentence_embedding_dimension())

    def _encode(self, texts: Sequence[str]) -> List[List[float]]:
        self.load()
        vectors = self._model.encode(list(texts), batch_size=self.batch_size, normalize_embeddings=True,
                                     show_progress_bar=False, convert_to_numpy=True)
        return [[float(x) for x in row] for row in vectors]

    def embed_passages(self, texts: Sequence[str]) -> List[List[float]]:
        return self._encode([self._passage_prefix + t for t in texts])

    def embed_query(self, text: str) -> List[float]:
        return self._encode([self._query_prefix + text])[0]


class Reranker:
    """Cross-encoder: scores (query, document) pairs jointly, 0..1 (sigmoid)."""

    def __init__(self, model_name: str, device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self._model = None
        self._lock = threading.Lock()

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:
                raise SemanticUnavailable(
                    "sentence-transformers is not installed (pip install -r backend/requirements-ai.txt)") from exc
            try:
                self._model = CrossEncoder(self.model_name, device=self.device)
            except Exception as exc:
                raise SemanticUnavailable(f"could not load reranker '{self.model_name}': {exc}") from exc

    def rerank(self, query: str, docs: Sequence[Tuple[int, str]]) -> Dict[int, float]:
        self.load()
        if not docs:
            return {}
        import math
        scores = self._model.predict([(query, text) for _, text in docs], show_progress_bar=False)
        out: Dict[int, float] = {}
        for (doc_id, _), raw in zip(docs, scores):
            raw = float(raw)
            # CrossEncoder already applies a sigmoid for single-logit models; squash only if it did not.
            out[doc_id] = raw if 0.0 <= raw <= 1.0 else 1.0 / (1.0 + math.exp(-raw))
        return out


_embedder: Optional[Embedder] = None
_reranker: Optional[Reranker] = None


def get_embedder() -> Optional[Embedder]:
    global _embedder
    if not settings.semantic_enabled:
        return None
    if _embedder is None:
        _embedder = Embedder(settings.EMBEDDING_MODEL, settings.EMBEDDING_DEVICE, settings.EMBEDDING_BATCH_SIZE)
    return _embedder


def get_reranker() -> Optional[Reranker]:
    global _reranker
    if not (settings.semantic_enabled and settings.RERANKER_ENABLED):
        return None
    if _reranker is None:
        _reranker = Reranker(settings.RERANKER_MODEL, settings.EMBEDDING_DEVICE)
    return _reranker


def set_models_for_tests(embedder, reranker) -> None:  # pragma: no cover - used by tests only
    global _embedder, _reranker
    _embedder, _reranker = embedder, reranker
