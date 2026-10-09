"""Call Center Agent - FastAPI application entry point."""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.core.metrics import metrics
from app.database import SessionLocal, create_all_tables
from app.routers import admin, auth, documents, pages, portal, staff, vonage
from app.seed import seed_all
from app.rag.semantic.index import semantic_index
from app.agent import followup

logger = logging.getLogger("call_center")


def _setup_logging() -> None:
    logging.basicConfig(level=logging.DEBUG if settings.DEBUG else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def _followup_worker(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.to_thread(followup.process_due)
        except Exception:  # keep the worker alive whatever happens
            logger.exception("follow-up worker iteration failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_logging()
    logger.info("Starting %s (database: %s)", settings.APP_NAME,
                "SQLite" if settings.is_sqlite else settings.DATABASE_URL.split("@")[-1])
    create_all_tables()
    with SessionLocal() as db:
        seed_all(db)
    if settings.semantic_enabled:
        semantic_index.request_sync()  # background: load the model, embed new/changed KB articles
        logger.info("Semantic search enabled (%s, store=%s, reranker=%s) - indexing in the background",
                    settings.EMBEDDING_MODEL, settings.VECTOR_STORE, "on" if settings.RERANKER_ENABLED else "off")
    else:
        logger.info("Semantic search is off (keyword BM25 only). Set EMBEDDING_PROVIDER=local to enable it")
    stop = asyncio.Event()
    worker = None
    if settings.followups_enabled:
        worker = asyncio.create_task(_followup_worker(stop))
        logger.info("Follow-up call worker started")
    else:
        logger.info("Follow-up calls are disabled (set FOLLOWUP_PROVIDER=vonage and the VONAGE_* values to enable)")
    try:
        yield
    finally:
        stop.set()
        if worker:
            await worker
        logger.info("%s stopped", settings.APP_NAME)


app = FastAPI(title=settings.APP_NAME, version="2.0.0",
              description="AI-assisted call center: customer portal + admin dashboard (SQLite).",
              lifespan=lifespan)

if settings.ALLOWED_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=settings.ALLOWED_ORIGINS, allow_credentials=False,
                       allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def timing_and_security_headers(request: Request, call_next):
    started = time.perf_counter()
    failed = False
    try:
        response = await call_next(request)
        failed = response.status_code >= 500
    except Exception:
        failed = True
        raise
    finally:
        path = request.url.path
        if path not in ("/", "/admin", "/index.html", "/admin.html", "/health", "/favicon.ico"):
            metrics.record("http.request", (time.perf_counter() - started) * 1000.0, error=failed)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "An internal server error occurred."})


for router in (pages.router, auth.router, portal.router, admin.router, documents.router, staff.router,
               vonage.router):
    app.include_router(router)
