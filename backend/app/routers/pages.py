"""Serves the two single-page front-ends and a health check."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import FRONTEND_DIR, settings
from app.database import get_db
from app.rag.semantic.index import semantic_index

router = APIRouter()

PAGE_HEADERS = {
    "Cache-Control": "no-cache",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
        "img-src 'self' data:; media-src 'self' data: blob:; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
}


def _page(name: str) -> FileResponse:
    path = FRONTEND_DIR / name
    if not path.is_file():
        raise HTTPException(404, f"{name} not found")
    return FileResponse(path, media_type="text/html; charset=utf-8", headers=PAGE_HEADERS)


@router.get("/", include_in_schema=False)
@router.get("/index.html", include_in_schema=False)
def customer_portal():
    return _page("index.html")


@router.get("/admin", include_in_schema=False)
@router.get("/admin.html", include_in_schema=False)
def admin_dashboard():
    return _page("admin.html")


@router.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


@router.get("/health", tags=["Health"])
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "database": "sqlite" if settings.is_sqlite else "other",
        "llm_configured": settings.llm_configured,
        "speech_configured": settings.speech_configured,
        "followup_calls": settings.followups_enabled,
        "semantic_search": semantic_index.status.state if settings.semantic_enabled else "off",
    }
