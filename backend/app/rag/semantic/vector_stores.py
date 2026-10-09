# Vector stores: SQLite (default, same database file) or Qdrant (REST, optional).

from __future__ import annotations

import hashlib
import logging
import math
import threading
from array import array
from typing import Dict, List, Optional, Sequence, Tuple

import httpx
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.config import settings
from app.database import SessionLocal
from app.models import KBEmbedding

logger = logging.getLogger("call_center")

try:  # numpy makes brute-force search fast; pure Python is the fallback
    import numpy as _np
except ImportError:  # pragma: no cover
    _np = None


def text_hash(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\n{text}".encode("utf-8")).hexdigest()


class VectorStore:
    name = "base"

    def prepare(self, dim: int) -> None: ...
    def existing(self) -> Dict[int, str]: ...
    def upsert(self, items: Sequence[Tuple[int, List[float], str]]) -> None: ...
    def delete(self, ids: Sequence[int]) -> None: ...
    def search(self, vector: Sequence[float], k: int) -> List[Tuple[int, float]]: ...
    def count(self) -> int: ...


# ---------------------------------------------------------------------------------- SQLite
class SQLiteVectorStore(VectorStore):
    """Vectors live in the ``kb_embeddings`` table. Search is an exact cosine scan (fine for a
    knowledge base of thousands of articles); vectors are normalised so cosine == dot product."""

    name = "sqlite"

    def __init__(self, model: str):
        self.model = model
        self._lock = threading.Lock()
        self._cache = {"sig": None, "ids": [], "matrix": None}

    def prepare(self, dim: int) -> None:
        with SessionLocal() as db:
            db.query(KBEmbedding).filter((KBEmbedding.model != self.model) | (KBEmbedding.dim != dim)).delete()
            db.commit()

    def existing(self) -> Dict[int, str]:
        with SessionLocal() as db:
            return {a: h for a, h in db.query(KBEmbedding.article_id, KBEmbedding.text_hash)
                    .filter(KBEmbedding.model == self.model).all()}

    def upsert(self, items) -> None:
        if not items:
            return
        try:
            self._write(items)
        except (IntegrityError, StaleDataError):
            # An article was deleted while its vector was being computed. Retry one by one and skip the
            # ones that vanished, so a deletion never fails the whole indexing run.
            for item in items:
                try:
                    self._write([item])
                except (IntegrityError, StaleDataError):
                    logger.info("article %s was deleted while being indexed; skipped", item[0])

    def _write(self, items) -> None:
        with SessionLocal() as db:
            for article_id, vector, thash in items:
                row = db.get(KBEmbedding, article_id)
                blob = array("f", vector).tobytes()
                if row is None:
                    db.add(KBEmbedding(article_id=article_id, model=self.model, dim=len(vector),
                                       text_hash=thash, vector=blob))
                else:
                    row.model, row.dim, row.text_hash, row.vector = self.model, len(vector), thash, blob
            db.commit()

    def delete(self, ids) -> None:
        if not ids:
            return
        with SessionLocal() as db:
            db.query(KBEmbedding).filter(KBEmbedding.article_id.in_(list(ids))).delete(synchronize_session=False)
            db.commit()

    def count(self) -> int:
        with SessionLocal() as db:
            return db.query(func.count(KBEmbedding.article_id)).filter(KBEmbedding.model == self.model).scalar() or 0

    def _load(self):
        with SessionLocal() as db:
            sig = db.query(func.count(KBEmbedding.article_id), func.max(KBEmbedding.updated_at)).filter(
                KBEmbedding.model == self.model).one()
            sig = (sig[0], str(sig[1]))
            with self._lock:
                if self._cache["sig"] == sig:
                    return self._cache["ids"], self._cache["matrix"]
                rows = db.query(KBEmbedding.article_id, KBEmbedding.vector).filter(
                    KBEmbedding.model == self.model).all()
                ids = [r[0] for r in rows]
                vectors = []
                for _, blob in rows:
                    arr = array("f")
                    arr.frombytes(blob)
                    vectors.append(arr)
                matrix = _np.array([list(v) for v in vectors], dtype="float32") if (_np is not None and vectors) else vectors
                self._cache.update(sig=sig, ids=ids, matrix=matrix)
                return ids, matrix

    def search(self, vector, k):
        ids, matrix = self._load()
        if not ids:
            return []
        if _np is not None:
            scores = matrix @ _np.array(vector, dtype="float32")
            order = _np.argsort(-scores)[:k]
            return [(ids[int(i)], float(scores[int(i)])) for i in order]
        scored = [(ids[i], sum(a * b for a, b in zip(matrix[i], vector))) for i in range(len(ids))]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]


# ---------------------------------------------------------------------------------- Qdrant
class QdrantStore(VectorStore):
    """Talks to Qdrant's REST API directly (no qdrant-client dependency)."""

    name = "qdrant"

    def __init__(self, url: str, collection: str, api_key: str = "", timeout: float = 20.0):
        self.url = url.rstrip("/")
        self.collection = collection
        headers = {"api-key": api_key} if api_key else {}
        self._http = httpx.Client(base_url=self.url, headers=headers, timeout=timeout)

    def _call(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Qdrant is unreachable at {self.url}: {exc}") from exc
        if response.status_code >= 400 and not (method == "GET" and response.status_code == 404):
            raise RuntimeError(f"Qdrant {method} {path} failed: {response.status_code} {response.text[:200]}")
        return {"status_code": response.status_code, **(response.json() if response.content else {})}

    def prepare(self, dim: int) -> None:
        info = self._call("GET", f"/collections/{self.collection}")
        if info["status_code"] == 200:
            vectors = (((info.get("result") or {}).get("config") or {}).get("params") or {}).get("vectors") or {}
            size = vectors.get("size") if isinstance(vectors, dict) else None
            if size == dim:
                return
            self._call("DELETE", f"/collections/{self.collection}")  # other model -> start over
        self._call("PUT", f"/collections/{self.collection}",
                   json={"vectors": {"size": dim, "distance": "Cosine"}})

    def existing(self) -> Dict[int, str]:
        found: Dict[int, str] = {}
        offset: Optional[object] = None
        while True:
            body = {"limit": 500, "with_payload": ["text_hash"], "with_vector": False}
            if offset is not None:
                body["offset"] = offset
            data = self._call("POST", f"/collections/{self.collection}/points/scroll", json=body)
            result = data.get("result") or {}
            for point in result.get("points", []):
                found[int(point["id"])] = (point.get("payload") or {}).get("text_hash", "")
            offset = result.get("next_page_offset")
            if offset is None:
                return found

    def upsert(self, items) -> None:
        if not items:
            return
        points = [{"id": int(i), "vector": list(v), "payload": {"text_hash": h}} for i, v, h in items]
        self._call("PUT", f"/collections/{self.collection}/points", params={"wait": "true"},
                   json={"points": points})

    def delete(self, ids) -> None:
        if ids:
            self._call("POST", f"/collections/{self.collection}/points/delete", params={"wait": "true"},
                       json={"points": [int(i) for i in ids]})

    def search(self, vector, k):
        data = self._call("POST", f"/collections/{self.collection}/points/search",
                          json={"vector": list(vector), "limit": int(k), "with_payload": False})
        return [(int(p["id"]), float(p["score"])) for p in data.get("result", [])]

    def count(self) -> int:
        data = self._call("POST", f"/collections/{self.collection}/points/count", json={"exact": True})
        return data.get("result", 0)


def build_store(model_name: str) -> VectorStore:
    if settings.VECTOR_STORE == "qdrant":
        return QdrantStore(url=settings.QDRANT_URL, collection=settings.QDRANT_COLLECTION,
                           api_key=settings.QDRANT_API_KEY)
    return SQLiteVectorStore(model_name)

