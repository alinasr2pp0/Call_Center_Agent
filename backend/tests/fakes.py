"""Deterministic stand-ins for the real local models (no downloads) + an in-memory fake Qdrant server."""
import json
import math
import re

import httpx

from app.rag.text import normalize, stem

# concept -> words. A query and an article that share a *concept* are "semantically" close even
# when they share no keyword, which is exactly what BM25 cannot do.
CONCEPTS = {
    "app_crash": ["تطبيق", "برنامج", "يقفل", "يغلق", "يتهنج", "هنج", "crash", "app", "اب"],
    "slow": ["بطيء", "بطي", "سرعه", "slow", "speed", "تقيل"],
    "no_connection": ["مقطوع", "فاصل", "انقطع", "offline", "مفيش", "احمر"],
    "wifi_password": ["باسورد", "كلمه", "سر", "password", "نسيت"],
    "bill": ["فاتوره", "فاتورة", "حساب", "bill", "invoice", "اعلي"],
    "cancel": ["الغاء", "الغي", "cancel", "اوقف"],
    "refund": ["استرداد", "رد", "refund"],
    "signal": ["شبكه", "اشاره", "signal", "network"],
}
_DIM = len(CONCEPTS) + 8


def _vector(text: str):
    norm = normalize(text)
    toks = re.findall(r"\w+", norm)
    stems = {stem(t) for t in toks} | set(toks)
    vec = [0.0] * _DIM
    for i, words in enumerate(CONCEPTS.values()):
        vec[i] = sum(1.0 for w in words if normalize(w) in stems or stem(normalize(w)) in stems)
    for tok in toks:  # tiny keyword component so unrelated texts are not identical
        vec[len(CONCEPTS) + (sum(map(ord, tok)) % 8)] += 0.01
    length = max(math.sqrt(sum(x * x for x in vec)), 1.0)  # keep hash-only vectors small
    return [x / length for x in vec]


class FakeEmbedder:
    model_name = "fake-e5"
    dim = _DIM
    calls = 0

    def load(self): ...

    def embed_passages(self, texts):
        FakeEmbedder.calls += len(texts)
        return [_vector(t) for t in texts]

    def embed_query(self, text):
        return _vector(text)


class FakeReranker:
    model_name = "fake-reranker"

    def load(self): ...

    def rerank(self, query, docs):
        q = _vector(query)
        return {i: max(0.0, sum(a * b for a, b in zip(q, _vector(t)))) for i, t in docs}


class FakeQdrant:
    """Implements just the Qdrant REST calls QdrantStore uses; plug in with httpx.MockTransport."""

    def __init__(self):
        self.collections = {}   # name -> {"size": int, "points": {id: (vector, payload)}}
        self.requests = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        self.requests.append((request.method, path))
        m = re.match(r"^/collections/([^/]+)(/.*)?$", path)
        name, rest = m.group(1), m.group(2) or ""
        col = self.collections.get(name)
        if rest == "":
            if request.method == "GET":
                if col is None:
                    return httpx.Response(404, json={"status": {"error": "Not found"}})
                return httpx.Response(200, json={"result": {"config": {"params": {"vectors": {
                    "size": col["size"], "distance": "Cosine"}}}}})
            if request.method == "PUT":
                self.collections[name] = {"size": body["vectors"]["size"], "points": {}}
                return httpx.Response(200, json={"result": True})
            if request.method == "DELETE":
                self.collections.pop(name, None)
                return httpx.Response(200, json={"result": True})
        if col is None:
            return httpx.Response(404, json={"status": {"error": "collection missing"}})
        if rest == "/points" and request.method == "PUT":
            for p in body["points"]:
                col["points"][p["id"]] = (p["vector"], p.get("payload", {}))
            return httpx.Response(200, json={"result": {"status": "completed"}})
        if rest == "/points/delete":
            for i in body["points"]:
                col["points"].pop(i, None)
            return httpx.Response(200, json={"result": {"status": "completed"}})
        if rest == "/points/scroll":
            ids = sorted(col["points"])
            start = body.get("offset", 0) or 0
            limit = body["limit"]
            chunk = ids[start:start + limit]
            nxt = start + limit if start + limit < len(ids) else None
            return httpx.Response(200, json={"result": {
                "points": [{"id": i, "payload": col["points"][i][1]} for i in chunk], "next_page_offset": nxt}})
        if rest == "/points/search":
            q = body["vector"]
            scored = sorted(((i, sum(a * b for a, b in zip(q, v))) for i, (v, _) in col["points"].items()),
                            key=lambda x: x[1], reverse=True)[:body["limit"]]
            return httpx.Response(200, json={"result": [{"id": i, "score": s} for i, s in scored]})
        if rest == "/points/count":
            return httpx.Response(200, json={"result": {"count": len(col["points"])}})
        return httpx.Response(400, json={"status": {"error": f"unsupported {request.method} {path}"}})
