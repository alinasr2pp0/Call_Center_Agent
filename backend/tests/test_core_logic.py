"""Pure-logic tests (no FastAPI/SQLAlchemy needed):  python -m unittest discover -s tests -p 'test_core*.py'"""
import os
import tempfile
import unittest

import _env  # noqa: F401  (must be first: sets up the test environment)

from app.rag.bm25 import KBDoc, KBIndex, pick_best  # noqa: E402
from app.core.metrics import MetricsRegistry  # noqa: E402
from app.core.security import (LoginRateLimiter, create_access_token, decode_access_token, hash_password,  # noqa: E402
                               sign_value, verify_password, verify_signature)
from app.rag.text import normalize, stem, tokenize  # noqa: E402


class TextTests(unittest.TestCase):
    def test_normalize_arabic_variants(self):
        self.assertEqual(normalize("أَحْمَد"), normalize("احمد"))
        self.assertEqual(normalize("الإنترنت"), normalize("الانترنت"))
        self.assertEqual(normalize("فاتورة"), normalize("فاتوره"))
        self.assertEqual(normalize("١٢٣"), "123")

    def test_stem_strips_article_and_plural(self):
        self.assertEqual(stem("الفاتوره"), stem("فاتوره"))
        self.assertEqual(stem("routers"), "router")

    def test_tokenize_drops_stopwords(self):
        toks = tokenize("الانترنت عندي بطيء جدا في البيت")
        self.assertIn("انترنت", toks)
        self.assertNotIn("في", toks)


def _docs():
    return [
        KBDoc(1, "إنترنت منزلي الإنترنت بطيء جدًا سرعة الإنترنت أقل من الباقة إعادة تشغيل الراوتر", True),
        KBDoc(2, "الفاتورة أعلى من المعتاد راجع تفاصيل الفاتورة من التطبيق", True),
        KBDoc(3, "راوتر نسيت كلمة سر الواي فاي تغيير كلمة المرور من صفحة الراوتر", True),
        KBDoc(4, "مشكلة بدون حل مسجل الانترنت فاصل", False),
        KBDoc(5, "Home Internet slow internet speed restart the router", True),
    ]


class KBSearchTests(unittest.TestCase):
    def setUp(self):
        self.index = KBIndex(_docs())

    def test_finds_right_article_with_arabic_variants(self):
        query = "الانترنت عندي بطيئ جدا"
        hits = self.index.search(query)
        self.assertIn(1, [h.doc_id for h in hits[:2]])
        texts = {d.id: d.text for d in _docs()}
        self.assertEqual(pick_best(hits, texts.__getitem__, query).doc_id, 1)  # Arabic question -> Arabic article

    def test_invoice_question(self):
        hits = self.index.search("ليه الفاتوره غالية الشهر ده")
        self.assertEqual(hits[0].doc_id, 2)

    def test_english_question(self):
        query = "my internet is slow"
        hits = self.index.search(query)
        texts = {d.id: d.text for d in _docs()}
        self.assertEqual(pick_best(hits, texts.__getitem__, query).doc_id, 5)

    def test_unrelated_question_has_low_coverage(self):
        hits = self.index.search("عايز احجز تذكره طيران الى باريس الاسبوع القادم")
        best = hits[0].coverage if hits else 0.0
        self.assertLess(best, 0.45)

    def test_articles_without_resolution_are_not_answers(self):
        ids = [h.doc_id for h in self.index.search("الانترنت فاصل")]
        self.assertNotIn(4, ids)
        ids = [h.doc_id for h in self.index.search("الانترنت فاصل", require_resolution=False)]
        self.assertIn(4, ids)

    def test_empty_index_and_empty_query(self):
        self.assertEqual(KBIndex([]).search("اي شيء"), [])
        self.assertEqual(self.index.search("   "), [])
        self.assertEqual(self.index.search("في من على"), [])  # only stopwords


class SecurityTests(unittest.TestCase):
    def test_password_hash_roundtrip(self):
        stored = hash_password("S3cret-pass")
        self.assertTrue(verify_password("S3cret-pass", stored))
        self.assertFalse(verify_password("wrong", stored))
        self.assertNotEqual(stored, hash_password("S3cret-pass"))  # salted

    def test_verify_rejects_garbage_hash(self):
        self.assertFalse(verify_password("x", "not-a-hash"))
        self.assertFalse(verify_password("x", ""))

    def test_jwt_roundtrip_and_tamper(self):
        token = create_access_token("user-1", "staff", {"role": "admin"})
        payload = decode_access_token(token)
        self.assertEqual(payload["sub"], "user-1")
        self.assertEqual(payload["kind"], "staff")
        self.assertIsNone(decode_access_token(token + "x"))
        self.assertIsNone(decode_access_token("garbage"))
        expired = create_access_token("user-1", "staff", expires_minutes=-1)
        self.assertIsNone(decode_access_token(expired))

    def test_signature(self):
        sig = sign_value("call:7")
        self.assertTrue(verify_signature("call:7", sig))
        self.assertFalse(verify_signature("call:8", sig))
        self.assertFalse(verify_signature("call:7", ""))

    def test_rate_limiter(self):
        limiter = LoginRateLimiter(3, 60)
        for _ in range(3):
            self.assertFalse(limiter.blocked("k"))
            limiter.fail("k")
        self.assertTrue(limiter.blocked("k"))
        self.assertFalse(limiter.blocked("other"))
        limiter.reset("k")
        self.assertFalse(limiter.blocked("k"))


class MetricsTests(unittest.TestCase):
    def test_percentiles_and_errors(self):
        reg = MetricsRegistry(window=100)
        for v in range(1, 101):
            reg.record("x", v)
        reg.record("y", 5, error=True)
        snap = reg.snapshot()
        self.assertEqual(snap["x"]["count"], 100)
        self.assertEqual(snap["x"]["p50_ms"], 50)
        self.assertEqual(snap["x"]["p95_ms"], 95)
        self.assertEqual(snap["x"]["p99_ms"], 99)
        self.assertAlmostEqual(snap["x"]["avg_ms"], 50.5)
        self.assertEqual(snap["y"]["errors"], 1)
        reg.clear()
        self.assertEqual(reg.snapshot(), {})

    def test_window_limit_and_timed(self):
        reg = MetricsRegistry(window=5)
        for v in range(10):
            reg.record("w", v)
        self.assertEqual(reg.snapshot()["w"]["samples"], 5)
        self.assertEqual(reg.snapshot()["w"]["count"], 10)
        with self.assertRaises(ValueError):
            with reg.timed("t"):
                raise ValueError("boom")
        self.assertEqual(reg.snapshot()["t"]["errors"], 1)


class ConfigTests(unittest.TestCase):
    def test_defaults_use_sqlite(self):
        from app.config import settings
        self.assertTrue(settings.is_sqlite)
        self.assertEqual(settings.APP_NAME, "Call Center Agent")
        self.assertFalse(settings.followups_enabled)

    def test_dotenv_parser(self):
        from pathlib import Path
        from app.config import _parse_dotenv
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / ".env"
            p.write_text('# c\nA=1\nB="two words"\nC=three # note\n\nBAD\n', encoding="utf-8")
            self.assertEqual(_parse_dotenv(p), {"A": "1", "B": "two words", "C": "three"})


if __name__ == "__main__":
    unittest.main()
