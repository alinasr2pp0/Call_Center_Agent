"""
Shared test environment initialization. Must be imported before any `app`
modules to ensure consistent configuration and test isolation.

Run the suite in both retrieval modes:
python -m unittest discover -s tests
EMBEDDING_PROVIDER=local python -m unittest discover -s tests
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

TMP = tempfile.mkdtemp(prefix="cca-test-")
for key, value in {
    "DATABASE_URL": "sqlite:///" + os.path.join(TMP, "test.db").replace("\\", "/"),
    "SECRET_KEY": "unit-test-secret-key-unit-test-secret-key",
    "SUPERADMIN_USERNAME": "superadmin",
    "SUPERADMIN_PASSWORD": "Sup3r-Admin-pass",
    "SEED_SAMPLE_KB": "true",
    "OPENROUTER_API_KEY": "",
    "GROQ_API_KEY": "",
    "TAVILY_API_KEY": "",
    "FOLLOWUP_PROVIDER": "none",
    "LOGIN_MAX_ATTEMPTS": "5",
    "EMBEDDING_PROVIDER": "none",
    "EMBEDDING_MODEL": "fake-e5",
    "VECTOR_MIN_SCORE": "0.6",
    "RERANKER_ENABLED": "true",
    "RERANK_MIN_SCORE": "0.5",
}.items():
    os.environ.setdefault(key, value)

SEMANTIC = os.environ["EMBEDDING_PROVIDER"] == "local"
if SEMANTIC:
    from fakes import FakeEmbedder, FakeReranker
    from app.rag.semantic import models as _models
    _models.set_models_for_tests(FakeEmbedder(), FakeReranker())
