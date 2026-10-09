"""Ticket workflow: customer message -> agent answer -> (optional) follow-up call."""
from __future__ import annotations

import time
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.core.metrics import metrics
from app.models import Customer, Escalation, Persona, Ticket, TicketCall, TicketMessage, utcnow
from app.agent import service as agent

SYSTEM_ESCALATED = "تم تسجيل المشكلة لفريق الدعم / The problem was passed to the support team"
SYSTEM_CONFIRMED = "تم تأكيد حل المشكلة ✓ / Resolution confirmed ✓"


def get_persona(db: Session, persona_id: Optional[str]) -> Optional[Persona]:
    if persona_id:
        persona = db.get(Persona, persona_id)
        if persona:
            return persona
    return (db.query(Persona).filter(Persona.is_default.is_(True)).order_by(Persona.sort_order).first()
            or db.query(Persona).order_by(Persona.sort_order).first())


def escalate_ticket(db: Session, ticket: Ticket, reason: str) -> None:
    """Mark a ticket as escalated, store the reason and tell the customer (system message)."""
    ticket.status = "escalated"
    ticket.closed_at = None
    db.add(Escalation(ticket_id=ticket.id, reason=reason))
    db.add(TicketMessage(ticket_id=ticket.id, sender="system", content=SYSTEM_ESCALATED))


def confirm_ticket(db: Session, ticket: Ticket) -> None:
    ticket.status = "resolved_confirmed"
    ticket.closed_at = utcnow()
    db.add(TicketMessage(ticket_id=ticket.id, sender="system", content=SYSTEM_CONFIRMED))


def handle_customer_message(db: Session, customer: Customer, problem_text: str,
                            persona_id: Optional[str]) -> dict:
    """Create a ticket for one customer message and answer it.  Returns the API response dict."""
    persona = get_persona(db, persona_id)

    # The (possibly slow) AI call happens BEFORE any write so no database lock is held meanwhile.
    started = time.perf_counter()
    result = agent.answer_problem(db, problem_text, persona)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    metrics.record("chat.time_to_first_answer", elapsed_ms)

    ticket = Ticket(
        customer_id=customer.id,
        persona_id=persona.id if persona else None,
        status="resolved_by_rag" if result.resolved else "open",
        category=result.category or "other",
        resolution_attempts=1,
        source=result.source,
        confidence=float(result.confidence or 0.0),
        used_web_search=result.used_web,
        initially_resolved=result.resolved,
        first_answer_ms=elapsed_ms,
    )
    db.add(ticket)
    db.flush()
    db.add(TicketMessage(ticket_id=ticket.id, sender="customer", content=problem_text))
    db.add(TicketMessage(ticket_id=ticket.id, sender="agent", content=result.answer))

    followup_in: Optional[int] = None
    if result.escalate:
        escalate_ticket(db, ticket, result.escalation_reason or "no confident answer")
    elif result.resolved and settings.followups_enabled and customer.phone:
        followup_in = settings.FOLLOWUP_DELAY_SECONDS
        db.add(TicketCall(ticket_id=ticket.id, attempt=1, status="scheduled",
                          scheduled_at=utcnow() + timedelta(seconds=followup_in)))
    db.commit()

    return {
        "ticket_id": ticket.id,
        "answer": result.answer,
        "source": result.source,
        "confidence": round(ticket.confidence, 4),
        "status": ticket.status,
        "followup_call_in_seconds": followup_in,
    }
