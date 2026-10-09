"""Hybrid search tests with fake local models (run with EMBEDDING_PROVIDER=local, see _env.py)."""
import unittest

import _env  # noqa: F401  (must be first)

import httpx
from fastapi.testclient import TestClient

from fakes import FakeEmbedder, FakeQdrant
from app.config import settings
from app.main import app
from app.rag.semantic.index import semantic_index
from app.rag.semantic.vector_stores import QdrantStore, SQLiteVectorStore, text_hash


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


@unittest.skipUnless(_env.SEMANTIC, "needs EMBEDDING_PROVIDER=local")
class HybridSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._ctx = TestClient(app)
        cls.client = cls._ctx.__enter__()
        assert semantic_index.wait_idle(30)
        r = cls.client.post("/auth/login", json={"username": "superadmin", "password": "Sup3r-Admin-pass"})
        cls.admin = bearer(r.json()["access_token"])
        r = cls.client.post("/customer-auth/signup", json={"username": "semcust", "password": "password123",
                                                           "phone": "01055556666"})
        cls.cust = bearer(r.json()["access_token"])

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def ask(self, text):
        r = self.client.post("/tickets/message", headers=self.cust, json={"problem_text": text})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_01_index_is_ready_and_reported(self):
        self.assertTrue(semantic_index.ready, semantic_index.status)
        self.assertEqual(semantic_index.reranker_ready, True)
        st = self.client.get("/admin/search/status", headers=self.admin).json()
        self.assertEqual(st["state"], "ready")
        self.assertEqual(st["indexed_articles"], 14)
        self.assertEqual(self.client.get("/health").json()["semantic_search"], "ready")

    def test_02_meaning_match_without_shared_keywords(self):
        # KB article: "التطبيق يقفل فجأة" ... the question uses other words (برنامج / يتهنج)
        body = {"product": "تطبيق", "ticket_type": "Technical issue", "subject": "التطبيق يقفل فجأة",
                "description": "تطبيق الخدمة يغلق نفسه بعد فتحه", "resolution": "حدّث التطبيق لآخر إصدار وأعد تثبيته.",
                "status": "Closed", "priority": "Medium", "channel": "Chat"}
        created = self.client.post("/admin/kb", headers=self.admin, json=body)
        self.assertEqual(created.status_code, 201)
        self.assertTrue(semantic_index.wait_idle(30))
        r = self.ask("البرنامج بتاع الشركة بيتهنج وبيقفل")
        self.assertEqual(r["source"], "kb")
        self.assertIn("حدّث التطبيق", r["answer"])
        # the new article was embedded; deleting it removes the vector too
        aid = created.json()["id"]
        self.assertEqual(self.client.delete(f"/admin/kb/{aid}", headers=self.admin).status_code, 200)
        self.assertTrue(semantic_index.wait_idle(30))
        self.assertEqual(self.client.get("/admin/search/status", headers=self.admin).json()["indexed_articles"], 14)

    def test_03_unrelated_question_still_escalates(self):
        r = self.ask("عايز اعرف مواعيد رحلات الطيران لباريس الاسبوع الجاي")
        self.assertEqual(r["status"], "escalated")

    def test_04_editing_an_article_reembeds_it(self):
        arts = self.client.get("/admin/kb", headers=self.admin).json()
        a = next(x for x in arts if x["subject"] == "الفاتورة أعلى من المعتاد")
        before = FakeEmbedder.calls
        a2 = dict(a, resolution=a["resolution"] + " تم التحديث.")
        self.assertEqual(self.client.put(f"/admin/kb/{a['id']}", headers=self.admin, json=a2).status_code, 200)
        self.assertTrue(semantic_index.wait_idle(30))
        self.assertEqual(FakeEmbedder.calls - before, 1)  # only the edited article, not the whole KB

    def test_05_reindex_endpoint_and_permissions(self):
        self.assertEqual(self.client.post("/admin/search/reindex", headers=self.admin).status_code, 200)
        self.assertEqual(self.client.post("/admin/search/reindex").status_code, 401)


@unittest.skipUnless(_env.SEMANTIC, "needs EMBEDDING_PROVIDER=local")
class StoreTests(unittest.TestCase):
    def test_sqlite_store_roundtrip(self):
        from app.database import SessionLocal
        from app.models import KBArticle
        with SessionLocal() as db:
            art = KBArticle(subject="s", description="d", resolution="r")
            db.add(art)
            db.commit()
            aid = art.id
        store = SQLiteVectorStore("fake-e5")
        emb = FakeEmbedder()
        v = emb.embed_passages(["الانترنت بطيء"])[0]
        store.prepare(len(v))
        before = store.count()
        store.upsert([(aid, v, text_hash("fake-e5", "x"))])
        self.assertEqual(store.existing()[aid], text_hash("fake-e5", "x"))
        self.assertEqual(store.count(), before + 1)
        top = store.search(v, 3)
        self.assertEqual(top[0][0], aid)
        self.assertGreater(top[0][1], 0.9)
        store.delete([aid])
        self.assertEqual(store.count(), before)
        with SessionLocal() as db:
            db.delete(db.get(KBArticle, aid))
            db.commit()

    def test_qdrant_store_against_fake_server(self):
        fake = FakeQdrant()
        store = QdrantStore("http://qdrant.test", "kb")
        store._http = httpx.Client(base_url="http://qdrant.test", transport=httpx.MockTransport(fake.handler))
        emb = FakeEmbedder()
        store.prepare(emb.dim)
        self.assertEqual(fake.collections["kb"]["size"], emb.dim)
        texts = ["الانترنت بطيء", "نسيت الباسورد", "الفاتورة اعلى"]
        vecs = emb.embed_passages(texts)
        store.upsert([(i + 1, v, f"h{i}") for i, v in enumerate(vecs)])
        self.assertEqual(store.count(), 3)
        self.assertEqual(store.existing(), {1: "h0", 2: "h1", 3: "h2"})
        self.assertEqual(store.search(emb.embed_query("باسورد الواي فاي"), 1)[0][0], 2)
        store.delete([2])
        self.assertEqual(set(store.existing()), {1, 3})
        store.prepare(emb.dim + 5)  # other model/dimension -> collection recreated empty
        self.assertEqual(store.count(), 0)

    def test_qdrant_unreachable_gives_clear_error(self):
        store = QdrantStore("http://qdrant.test", "kb")
        def boom(request):
            raise httpx.ConnectError("refused")
        store._http = httpx.Client(base_url="http://qdrant.test", transport=httpx.MockTransport(boom))
        with self.assertRaises(RuntimeError) as ctx:
            store.count()
        self.assertIn("unreachable", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
