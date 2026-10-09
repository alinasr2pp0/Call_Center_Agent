"""SQLite (default) database engine, session factory and table creation."""
from __future__ import annotations

from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = settings.DATABASE_URL
    kwargs = {}
    if settings.is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        # make sure the folder of the database file exists
        from sqlalchemy.engine import make_url
        db_path = make_url(url).database
        if db_path and db_path != ":memory:":
            Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    else:
        kwargs["pool_pre_ping"] = True
    return create_engine(url, **kwargs)


engine = _make_engine()

if settings.is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - trivial
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def upgrade_schema(bind=None) -> None:
    """Add columns that older databases lack (``create_all`` only creates missing *tables*).

    Safe to run on every start: it does nothing when the schema is already current.
    """
    bind = bind or engine
    inspector = inspect(bind)
    if "kb_articles" in inspector.get_table_names():
        columns = {c["name"] for c in inspector.get_columns("kb_articles")}
        if "document_id" not in columns:
            with bind.begin() as conn:
                conn.execute(text("ALTER TABLE kb_articles ADD COLUMN document_id VARCHAR(36) "
                                  "REFERENCES documents(id) ON DELETE CASCADE"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_kb_articles_document_id "
                                  "ON kb_articles (document_id)"))


def create_all_tables() -> None:
    import app.models  # noqa: F401  (register all tables on Base.metadata)

    Base.metadata.create_all(bind=engine)
    upgrade_schema()
