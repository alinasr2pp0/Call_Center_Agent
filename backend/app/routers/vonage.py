"""Public webhooks called by Vonage during follow-up calls (protected by an HMAC signature)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.security import verify_signature
from app.database import get_db
from app.models import TicketCall
from app.agent import followup

router = APIRouter(prefix="/vonage", tags=["Vonage"])


async def _json_body(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _verified_call(db: Session, call_id: int, sig: str) -> TicketCall:
    if not verify_signature(f"call:{call_id}", sig):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid signature")
    call = db.get(TicketCall, call_id)
    if call is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Call not found")
    return call


@router.post("/event")
async def call_event(request: Request, call_id: int = Query(...), sig: str = Query(""),
                     db: Session = Depends(get_db)):
    body = await _json_body(request)
    call = _verified_call(db, call_id, sig)
    duration: Optional[int] = None
    try:
        duration = int(body["duration"]) if body.get("duration") not in (None, "") else None
    except (TypeError, ValueError):
        duration = None
    followup.handle_event(db, call, str(body.get("status", "")), duration)
    return JSONResponse({"ok": True})


@router.post("/input")
async def call_input(request: Request, call_id: int = Query(...), sig: str = Query(""),
                     attempt: int = Query(0, ge=0, le=5), db: Session = Depends(get_db)):
    body = await _json_body(request)
    call = _verified_call(db, call_id, sig)
    dtmf = body.get("dtmf")
    digits = ""
    if isinstance(dtmf, dict):
        digits = str(dtmf.get("digits") or "")
    elif isinstance(dtmf, str):
        digits = dtmf
    return JSONResponse(followup.handle_input(db, call, digits, attempt))
