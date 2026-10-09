"""
Automated follow-up phone calls (Vonage Voice API, DTMF based).

Flow
----
1. A resolved ticket gets a ``TicketCall`` row (status ``scheduled``).
2. ``process_due`` (run every few seconds by the background worker) dials due calls.
3. The customer hears an Arabic question and presses **1** (solved) or **2** (not solved).
4. Vonage posts the result to ``/vonage/input`` and call-progress events to ``/vonage/event``.

If nobody answers the call is retried (``FOLLOWUP_MAX_ATTEMPTS``) and then escalated to a human.
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

import httpx
import jwt
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT, settings
from app.core.metrics import metrics
from app.core.security import sign_value
from app.database import SessionLocal
from app.models import TicketCall, as_utc, utcnow
from app.agent import tickets
from app.agent.errors import ExternalServiceError

logger = logging.getLogger("call_center")

VONAGE_CALLS_URL = "https://api.nexmo.com/v1/calls"

GREETING = ("السلام عليكم. معاك مركز خدمة العملاء. بنتابع معاك بخصوص المشكلة اللي سجلتها. "
            "لو المشكلة اتحلت اضغط واحد. ولو لسه موجودة اضغط اتنين.")
REPEAT = "معلش، ماسمعتش اختيارك. اضغط واحد لو المشكلة اتحلت، أو اتنين لو لسه موجودة."
THANKS_RESOLVED = "تمام جدًا، سعيدين إن المشكلة اتحلت. شكرًا لوقتك ومع السلامة."
THANKS_ESCALATED = "حاضر، هنبلغ فريق الدعم وهيتواصلوا معاك في أقرب وقت. شكرًا لوقتك ومع السلامة."
THANKS_NO_INPUT = "مفيش رد، هنبلغ فريق الدعم يتواصل معاك. مع السلامة."


# ------------------------------------------------------------------ helpers
def normalize_phone(phone: str) -> str:
    """Digits only, international format without '+' (Egyptian local 01xxxxxxxxx -> 201xxxxxxxxx)."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = "2" + digits
    return digits


def call_signature(call_id: int) -> str:
    return sign_value(f"call:{call_id}")


def _webhook_url(path: str, call_id: int, **extra) -> str:
    query = f"call_id={call_id}&sig={call_signature(call_id)}" + "".join(f"&{k}={v}" for k, v in extra.items())
    return f"{settings.PUBLIC_BASE_URL}{path}?{query}"


def build_ncco(call_id: int, attempt: int = 0) -> List[dict]:
    return [
        {"action": "talk", "text": GREETING if attempt == 0 else REPEAT, "language": "ar", "bargeIn": False},
        {
            "action": "input",
            "type": ["dtmf"],
            "dtmf": {"maxDigits": 1, "timeOut": 8, "submitOnHash": False},
            "eventUrl": [_webhook_url("/vonage/input", call_id, attempt=attempt)],
            "eventMethod": "POST",
        },
    ]


def talk_ncco(text: str) -> List[dict]:
    return [{"action": "talk", "text": text, "language": "ar"}]


@lru_cache(maxsize=1)
def _private_key() -> str:
    path = Path(settings.VONAGE_PRIVATE_KEY_PATH).expanduser()
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    if not path.is_file():
        raise ExternalServiceError(f"Vonage private key not found: {path}")
    return path.read_text(encoding="utf-8")


def _vonage_jwt() -> str:
    now = int(time.time())
    payload = {"application_id": settings.VONAGE_APPLICATION_ID, "iat": now, "exp": now + 300,
               "jti": str(uuid.uuid4())}
    return jwt.encode(payload, _private_key(), algorithm="RS256")


def _create_vonage_call(to_number: str, call_id: int) -> str:
    body = {
        "to": [{"type": "phone", "number": to_number}],
        "from": {"type": "phone", "number": normalize_phone(settings.VONAGE_FROM_NUMBER)},
        "ncco": build_ncco(call_id),
        "event_url": [_webhook_url("/vonage/event", call_id)],
        "event_method": "POST",
    }
    try:
        with metrics.timed("api.vonage.create_call"):
            response = httpx.post(VONAGE_CALLS_URL, json=body,
                                  headers={"Authorization": f"Bearer {_vonage_jwt()}"}, timeout=20.0)
            response.raise_for_status()
            return str(response.json().get("uuid", ""))
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Vonage create call failed: %s", exc)
        raise ExternalServiceError("Vonage call failed") from exc


# ------------------------------------------------------------------ call lifecycle
def _is_final(call: TicketCall) -> bool:
    return call.status in ("completed", "no_answer", "failed")


def place_call(db: Session, call: TicketCall) -> None:
    ticket = call.ticket
    to_number = normalize_phone(settings.VONAGE_TEST_TO_NUMBER or ticket.customer.phone)
    call.status = "in_progress"
    call.started_at = utcnow()
    db.commit()  # commit first so a crash can never cause the customer to be dialled twice
    if not to_number:
        mark_unreachable(db, call, failed=True)
        return
    try:
        call.provider_call_id = _create_vonage_call(to_number, call.id)
        db.commit()
    except ExternalServiceError:
        mark_unreachable(db, call, failed=True)


def mark_unreachable(db: Session, call: TicketCall, failed: bool = False) -> None:
    """The customer could not be reached: retry later, or escalate after the last attempt."""
    if _is_final(call):
        return
    call.ended_at = utcnow()
    call.answered = False
    ticket = call.ticket
    if call.attempt < settings.FOLLOWUP_MAX_ATTEMPTS:
        call.status = "failed" if failed else "no_answer"
        db.add(TicketCall(ticket_id=ticket.id, attempt=call.attempt + 1, status="scheduled",
                          scheduled_at=utcnow() + timedelta(seconds=settings.FOLLOWUP_RETRY_DELAY_SECONDS)))
    else:
        call.status = "completed"
        call.outcome = "escalated_to_agent"
        tickets.escalate_ticket(db, ticket, f"customer unreachable after {call.attempt} call attempt(s)")
    db.commit()


def complete_call(db: Session, call: TicketCall, outcome: str, dtmf: Optional[str] = None,
                  duration: Optional[int] = None) -> None:
    """The customer answered and gave an answer (or never did)."""
    if _is_final(call):
        return
    call.status = "completed"
    call.outcome = outcome
    call.answered = True
    call.dtmf = dtmf
    call.ended_at = utcnow()
    if duration is None and call.started_at:
        duration = int((call.ended_at - as_utc(call.started_at)).total_seconds())
    call.duration_seconds = max(0, duration or 0)
    ticket = call.ticket
    if outcome == "resolved_confirmed":
        tickets.confirm_ticket(db, ticket)
    elif outcome == "transferred_to_agent":
        tickets.escalate_ticket(db, ticket, "customer said the problem is still not solved")
    else:
        tickets.escalate_ticket(db, ticket, "customer answered the call but gave no answer")
    db.commit()


def handle_input(db: Session, call: TicketCall, digits: str, attempt: int) -> List[dict]:
    """Process the DTMF result and return the NCCO to play next."""
    digits = (digits or "").strip()
    if digits == "1":
        complete_call(db, call, "resolved_confirmed", dtmf=digits)
        return talk_ncco(THANKS_RESOLVED)
    if digits == "2":
        complete_call(db, call, "transferred_to_agent", dtmf=digits)
        return talk_ncco(THANKS_ESCALATED)
    if attempt < 1 and not _is_final(call):
        call.answered = True
        db.commit()
        return build_ncco(call.id, attempt=attempt + 1)
    complete_call(db, call, "escalated_to_agent", dtmf=digits or None)
    return talk_ncco(THANKS_NO_INPUT)


def handle_event(db: Session, call: TicketCall, status: str, duration: Optional[int]) -> None:
    status = (status or "").lower()
    if status == "answered":
        if not _is_final(call):
            call.answered = True
            db.commit()
    elif status in ("busy", "cancelled", "failed", "rejected", "timeout", "unanswered", "machine"):
        mark_unreachable(db, call, failed=status in ("failed", "rejected"))
    elif status == "completed":
        if not _is_final(call):
            if call.answered:
                complete_call(db, call, "escalated_to_agent", duration=duration)
            else:
                mark_unreachable(db, call)
    elif status == "started" or status == "ringing":
        pass


# ------------------------------------------------------------------ background worker step
def process_due() -> int:
    """Dial due calls and clean up calls stuck in progress.  Returns how many calls were dialled."""
    if not settings.followups_enabled:
        return 0
    dialled = 0
    with SessionLocal() as db:
        now = utcnow()
        due = (db.query(TicketCall).filter(TicketCall.status == "scheduled", TicketCall.scheduled_at <= now)
               .order_by(TicketCall.scheduled_at).limit(10).all())
        for call in due:
            place_call(db, call)
            dialled += 1
        stale_before = now - timedelta(seconds=settings.FOLLOWUP_CALL_TIMEOUT_SECONDS)
        stuck = (db.query(TicketCall).filter(TicketCall.status == "in_progress", TicketCall.started_at <= stale_before)
                 .limit(20).all())
        for call in stuck:
            if call.answered:
                complete_call(db, call, "escalated_to_agent")
            else:
                mark_unreachable(db, call)
    return dialled
