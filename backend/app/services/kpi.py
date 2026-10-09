"""Dashboard numbers computed from real data only (``None`` when there is nothing to measure)."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.metrics import metrics
from app.models import Document, KBArticle, Ticket, TicketCall

RESOLVED_STATUSES = ("resolved_by_rag", "resolved_confirmed")


def _pct(part: int, whole: int) -> Optional[float]:
    return round(part * 100.0 / whole, 2) if whole else None


def ticket_stats(db: Session) -> dict:
    total = db.query(func.count(Ticket.id)).scalar() or 0
    counts = dict(db.query(Ticket.status, func.count(Ticket.id)).group_by(Ticket.status).all())
    return {
        "total": total,
        "resolved": sum(counts.get(s, 0) for s in RESOLVED_STATUSES),
        "escalated": counts.get("escalated", 0),
        "open": counts.get("open", 0),
    }


def dashboard_metrics(db: Session) -> dict:
    total = db.query(func.count(Ticket.id)).scalar() or 0
    escalated = db.query(func.count(Ticket.id)).filter(Ticket.status == "escalated").scalar() or 0
    initially_resolved = db.query(func.count(Ticket.id)).filter(Ticket.initially_resolved.is_(True)).scalar() or 0
    web_used = db.query(func.count(Ticket.id)).filter(Ticket.used_web_search.is_(True)).scalar() or 0

    total_calls = db.query(func.count(TicketCall.id)).filter(TicketCall.status != "scheduled").scalar() or 0
    finished = db.query(TicketCall).filter(TicketCall.status.in_(("completed", "no_answer", "failed")))

    # first attempts that finished: how many were answered
    first_attempts = finished.filter(TicketCall.attempt == 1)
    first_total = first_attempts.count()
    first_answered = first_attempts.filter(TicketCall.answered.is_(True)).count()

    # FCR: among tickets whose first call was answered, how many were confirmed solved
    first_confirmed = first_attempts.filter(TicketCall.answered.is_(True),
                                            TicketCall.outcome == "resolved_confirmed").count()

    completed = db.query(TicketCall).filter(TicketCall.status == "completed")
    completed_total = completed.count()
    completed_auto = completed.filter(TicketCall.outcome.in_(("resolved_confirmed", "transferred_to_agent"))).count()

    avg_duration = (db.query(func.avg(TicketCall.duration_seconds))
                    .filter(TicketCall.answered.is_(True), TicketCall.duration_seconds.isnot(None)).scalar())

    breakdown = (db.query(Ticket.category, func.count(Ticket.id)).group_by(Ticket.category)
                 .order_by(func.count(Ticket.id).desc()).limit(20).all())

    return {
        "fcr_rate": _pct(first_confirmed, first_answered),
        "escalation_rate": _pct(escalated, total),
        "text_resolution_rate": _pct(initially_resolved, total),
        "call_completion_rate": _pct(completed_auto, completed_total),
        "avg_handle_time_seconds": float(avg_duration) if avg_duration is not None else None,
        "call_reachability_rate": _pct(first_answered, first_total),
        "web_search_fallback_rate": _pct(web_used, total),
        # retrieval-quality scores need a labelled evaluation set; none is configured, so no fake numbers
        "precision": None,
        "recall": None,
        "faithfulness": None,
        "total_tickets": total,
        "total_calls": total_calls,
        "kb_article_count": db.query(func.count(KBArticle.id)).filter(KBArticle.document_id.is_(None)).scalar() or 0,
        "document_count": db.query(func.count(Document.id)).scalar() or 0,
        "category_breakdown": [{"category": c or "other", "count": n} for c, n in breakdown],
        "performance": metrics.snapshot(),
    }
