"""
Centralized application configuration with prioritized environment-variable
and .env resolution, secure configuration management, and SQLite as the
default database backend (`data/call_center.db`).
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

# backend/app/config.py -> parents[0]=app, [1]=backend, [2]=project root
BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DATA_DIR = PROJECT_ROOT / "data"

_PLACEHOLDER_SECRETS = {"", "change-me", "change-me-to-a-long-random-secret-key",
                        "your_super_secret_jwt_key_change_this_in_production"}


def _parse_dotenv(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if value and value[0] in "\"'" and value.endswith(value[0]) and len(value) >= 2:
            value = value[1:-1]
        else:  # strip trailing inline comment for unquoted values
            value = value.split(" #", 1)[0].strip()
        values[key] = value
    return values


def _collect_env() -> Dict[str, str]:
    merged: Dict[str, str] = {}
    merged.update(_parse_dotenv(BACKEND_ROOT / ".env"))
    merged.update(_parse_dotenv(PROJECT_ROOT / ".env"))
    merged.update({k: v for k, v in os.environ.items()})
    return merged


def _bool(value: str, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _float(value: str, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _load_secret_key(env: Dict[str, str]) -> str:
    configured = env.get("SECRET_KEY", "").strip()
    if configured not in _PLACEHOLDER_SECRETS:
        return configured
    # No usable key configured: create one once and keep it, so tokens survive restarts.
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key_file = DATA_DIR / ".secret_key"
    if key_file.is_file():
        stored = key_file.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    generated = secrets.token_urlsafe(48)
    key_file.write_text(generated, encoding="utf-8")
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return generated


@dataclass(frozen=True)
class Settings:
    APP_NAME: str
    DEBUG: bool
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    ALLOWED_ORIGINS: List[str]
    BACKEND_HOST: str
    BACKEND_PORT: int
    PUBLIC_BASE_URL: str

    SUPERADMIN_USERNAME: str
    SUPERADMIN_PASSWORD: str
    SEED_SAMPLE_KB: bool

    LOGIN_MAX_ATTEMPTS: int
    LOGIN_WINDOW_SECONDS: int

    OPENROUTER_API_KEY: str          # the Agent's language model
    OPENROUTER_MODEL: str
    OPENROUTER_BASE_URL: str
    OPENROUTER_REFERER: str
    GROQ_API_KEY: str                # speech only: speech-to-text + text-to-speech
    WHISPER_MODEL: str
    STT_LANGUAGE: str
    GROQ_TTS_MODEL: str
    GROQ_TTS_VOICE: str
    TAVILY_API_KEY: str
    KB_CONFIDENCE_THRESHOLD: float

    # semantic search (all optional; BM25 keyword search is always available)
    EMBEDDING_PROVIDER: str          # "none" | "local"
    EMBEDDING_MODEL: str
    EMBEDDING_DEVICE: str
    EMBEDDING_BATCH_SIZE: int
    VECTOR_STORE: str                # "sqlite" | "qdrant"
    QDRANT_URL: str
    QDRANT_API_KEY: str
    QDRANT_COLLECTION: str
    VECTOR_MIN_SCORE: float          # minimum cosine similarity to trust a semantic match (0 = auto per model)
    RERANKER_ENABLED: bool
    RERANKER_MODEL: str
    RERANK_MIN_SCORE: float
    HYBRID_CANDIDATES: int
    HYBRID_BM25_WEIGHT: float
    HYBRID_VECTOR_WEIGHT: float

    FOLLOWUP_PROVIDER: str  # "none" | "vonage"
    FOLLOWUP_DELAY_SECONDS: int
    FOLLOWUP_RETRY_DELAY_SECONDS: int
    FOLLOWUP_MAX_ATTEMPTS: int
    FOLLOWUP_CALL_TIMEOUT_SECONDS: int

    VONAGE_APPLICATION_ID: str
    VONAGE_PRIVATE_KEY_PATH: str
    VONAGE_FROM_NUMBER: str
    VONAGE_TEST_TO_NUMBER: str

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def llm_configured(self) -> bool:
        return bool(self.OPENROUTER_API_KEY)

    @property
    def speech_configured(self) -> bool:
        return bool(self.GROQ_API_KEY)

    @property
    def vonage_configured(self) -> bool:
        return bool(self.VONAGE_APPLICATION_ID and self.VONAGE_PRIVATE_KEY_PATH and self.VONAGE_FROM_NUMBER)

    @property
    def semantic_enabled(self) -> bool:
        return self.EMBEDDING_PROVIDER == "local"

    @property
    def vector_min_score(self) -> float:
        if self.VECTOR_MIN_SCORE > 0:
            return self.VECTOR_MIN_SCORE
        # e5 models give compressed cosine scores (~0.7-0.9); bge-m3 style models are wider.
        return 0.55 if "bge" in self.EMBEDDING_MODEL.lower() else 0.80

    @property
    def followups_enabled(self) -> bool:
        return self.FOLLOWUP_PROVIDER == "vonage" and self.vonage_configured

    @classmethod
    def load(cls) -> "Settings":
        env = _collect_env()
        default_db = "sqlite:///" + (DATA_DIR / "call_center.db").as_posix()
        database_url = env.get("DATABASE_URL", "").strip() or default_db
        origins = [o.strip() for o in env.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
        host = env.get("BACKEND_HOST", "127.0.0.1").strip() or "127.0.0.1"
        port = _int(env.get("BACKEND_PORT", "8000"), 8000)
        provider = env.get("FOLLOWUP_PROVIDER", "none").strip().lower() or "none"
        return cls(
            APP_NAME=env.get("APP_NAME", "Call Center Agent").strip() or "Call Center Agent",
            DEBUG=_bool(env.get("DEBUG", ""), False),
            DATABASE_URL=database_url,
            SECRET_KEY=_load_secret_key(env),
            ALGORITHM="HS256",
            ACCESS_TOKEN_EXPIRE_MINUTES=_int(env.get("ACCESS_TOKEN_EXPIRE_MINUTES", "480"), 480),
            ALLOWED_ORIGINS=origins,
            BACKEND_HOST=host,
            BACKEND_PORT=port,
            PUBLIC_BASE_URL=env.get("PUBLIC_BASE_URL", f"http://localhost:{port}").strip().rstrip("/"),
            SUPERADMIN_USERNAME=env.get("SUPERADMIN_USERNAME", "superadmin").strip() or "superadmin",
            SUPERADMIN_PASSWORD=env.get("SUPERADMIN_PASSWORD", ""),
            SEED_SAMPLE_KB=_bool(env.get("SEED_SAMPLE_KB", ""), True),
            LOGIN_MAX_ATTEMPTS=_int(env.get("LOGIN_MAX_ATTEMPTS", "8"), 8),
            LOGIN_WINDOW_SECONDS=_int(env.get("LOGIN_WINDOW_SECONDS", "300"), 300),
            OPENROUTER_API_KEY=env.get("OPENROUTER_API_KEY", "").strip(),
            OPENROUTER_MODEL=env.get("OPENROUTER_MODEL", "openai/gpt-oss-20b").strip() or "openai/gpt-oss-20b",
            OPENROUTER_BASE_URL=(env.get("OPENROUTER_BASE_URL", "").strip()
                                 or "https://openrouter.ai/api/v1").rstrip("/"),
            OPENROUTER_REFERER=env.get("OPENROUTER_REFERER", "").strip(),
            GROQ_API_KEY=env.get("GROQ_API_KEY", "").strip(),
            WHISPER_MODEL=env.get("WHISPER_MODEL", "whisper-large-v3-turbo").strip(),
            STT_LANGUAGE=env.get("STT_LANGUAGE", "ar").strip(),
            GROQ_TTS_MODEL=env.get("GROQ_TTS_MODEL", "playai-tts-arabic").strip(),
            GROQ_TTS_VOICE=env.get("GROQ_TTS_VOICE", "Ahmad-PlayAI").strip(),
            TAVILY_API_KEY=env.get("TAVILY_API_KEY", "").strip(),
            KB_CONFIDENCE_THRESHOLD=_float(env.get("KB_CONFIDENCE_THRESHOLD", "0.45"), 0.45),
            EMBEDDING_PROVIDER=(env.get("EMBEDDING_PROVIDER", "none").strip().lower() or "none"),
            EMBEDDING_MODEL=env.get("EMBEDDING_MODEL", "intfloat/multilingual-e5-small").strip(),
            EMBEDDING_DEVICE=env.get("EMBEDDING_DEVICE", "cpu").strip() or "cpu",
            EMBEDDING_BATCH_SIZE=max(1, _int(env.get("EMBEDDING_BATCH_SIZE", "16"), 16)),
            VECTOR_STORE=(env.get("VECTOR_STORE", "sqlite").strip().lower() or "sqlite"),
            QDRANT_URL=env.get("QDRANT_URL", "http://localhost:6333").strip().rstrip("/"),
            QDRANT_API_KEY=env.get("QDRANT_API_KEY", "").strip(),
            QDRANT_COLLECTION=env.get("QDRANT_COLLECTION", "call_center_kb").strip() or "call_center_kb",
            VECTOR_MIN_SCORE=_float(env.get("VECTOR_MIN_SCORE", "0"), 0.0),
            RERANKER_ENABLED=_bool(env.get("RERANKER_ENABLED", ""), False),
            RERANKER_MODEL=env.get("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3").strip(),
            RERANK_MIN_SCORE=_float(env.get("RERANK_MIN_SCORE", "0.35"), 0.35),
            HYBRID_CANDIDATES=min(50, max(3, _int(env.get("HYBRID_CANDIDATES", "10"), 10))),
            HYBRID_BM25_WEIGHT=_float(env.get("HYBRID_BM25_WEIGHT", "1.0"), 1.0),
            HYBRID_VECTOR_WEIGHT=_float(env.get("HYBRID_VECTOR_WEIGHT", "1.0"), 1.0),
            FOLLOWUP_PROVIDER=provider,
            FOLLOWUP_DELAY_SECONDS=max(0, _int(env.get("FOLLOWUP_DELAY_SECONDS", "180"), 180)),
            FOLLOWUP_RETRY_DELAY_SECONDS=max(0, _int(env.get("FOLLOWUP_RETRY_DELAY_SECONDS", "300"), 300)),
            FOLLOWUP_MAX_ATTEMPTS=max(1, _int(env.get("FOLLOWUP_MAX_ATTEMPTS", "2"), 2)),
            FOLLOWUP_CALL_TIMEOUT_SECONDS=max(60, _int(env.get("FOLLOWUP_CALL_TIMEOUT_SECONDS", "600"), 600)),
            VONAGE_APPLICATION_ID=env.get("VONAGE_APPLICATION_ID", "").strip(),
            VONAGE_PRIVATE_KEY_PATH=env.get("VONAGE_PRIVATE_KEY_PATH", "").strip(),
            VONAGE_FROM_NUMBER=env.get("VONAGE_FROM_NUMBER", "").strip(),
            VONAGE_TEST_TO_NUMBER=env.get("VONAGE_TEST_TO_NUMBER", "").strip(),
        )


settings = Settings.load()
