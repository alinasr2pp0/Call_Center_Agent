"""Admin dashboard API: stats, metrics, tickets, knowledge base, customers, personas, reset."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.core.metrics import metrics
from app.core.security import hash_password
from app.database import get_db
from app.deps import ADMIN_ROLES, require_staff
from app.models import (Customer, Escalation, KBArticle, Persona, StaffUser, Ticket, TicketCall, TicketMessage,
                        iso)
from app.routers.auth import call_dict
from app.schemas import ActiveFlag, KBArticleIn, PasswordReset, PersonaUpdate
from app.rag.semantic.index import semantic_index
from app.agent import service as agent
from app.services import kpi

router = APIRouter(prefix="/admin", tags=["Admin"])

any_staff = require_staff()                 # superadmin, admin, agent
admins_only = require_staff(*ADMIN_ROLES)   # superadmin, admin


# ------------------------------------------------------------------ stats / metrics
@router.get("/stats")
def stats(_: StaffUser = Depends(any_staff), db: Session = Depends(get_db)):
    return kpi.ticket_stats(db)


@router.get("/metrics")
def dashboard_metrics(_: StaffUser = Depends(admins_only), db: Session = Depends(get_db)):
    return kpi.dashboard_metrics(db)


# ------------------------------------------------------------------ tickets
@router.get("/tickets")
def list_tickets(limit: int = Query(500, ge=1, le=2000), _: StaffUser = Depends(any_staff),
                 db: Session = Depends(get_db)):
    rows = db.query(Ticket).order_by(Ticket.opened_at.desc()).limit(limit).all()
    return [{"id": t.id, "status": t.status, "category": t.category,
             "resolution_attempts": t.resolution_attempts, "opened_at": iso(t.opened_at)} for t in rows]


@router.get("/tickets/{ticket_id}")
def ticket_detail(ticket_id: str, _: StaffUser = Depends(any_staff), db: Session = Depends(get_db)):
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    return {
        "ticket": {"id": ticket.id, "status": ticket.status, "category": ticket.category,
                   "source": ticket.source, "confidence": ticket.confidence,
                   "resolution_attempts": ticket.resolution_attempts, "opened_at": iso(ticket.opened_at),
                   "customer": ticket.customer.username if ticket.customer else None},
        "messages": [{"sender": m.sender, "content": m.content, "created_at": iso(m.created_at)}
                     for m in ticket.messages],
        "calls": [call_dict(c) for c in ticket.calls],
        "escalations": [{"reason": e.reason, "created_at": iso(e.created_at)} for e in ticket.escalations],
    }


# ------------------------------------------------------------------ knowledge base
def kb_dict(a: KBArticle) -> dict:
    return {"id": a.id, "product": a.product, "ticket_type": a.ticket_type, "subject": a.subject,
            "description": a.description, "resolution": a.resolution, "status": a.status,
            "priority": a.priority, "channel": a.channel}


def _apply_kb(article: KBArticle, body: KBArticleIn) -> None:
    article.product = body.product
    article.ticket_type = body.ticket_type
    article.subject = body.subject
    article.description = body.description
    article.resolution = body.resolution or None
    article.status = body.status
    article.priority = body.priority
    article.channel = body.channel


def _manual_article_or_404(db: Session, article_id: int) -> KBArticle:
    """An article written by hand. Chunks of uploaded documents are managed through /admin/documents."""
    article = db.get(KBArticle, article_id)
    if article is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Article not found")
    if article.document_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This text comes from an uploaded document: edit or delete the document instead")
    return article


@router.get("/kb")
def list_kb(_: StaffUser = Depends(any_staff), db: Session = Depends(get_db)):
    rows = db.query(KBArticle).filter(KBArticle.document_id.is_(None)).order_by(KBArticle.id).all()
    return [kb_dict(a) for a in rows]


@router.post("/kb", status_code=status.HTTP_201_CREATED)
def create_kb(body: KBArticleIn, _: StaffUser = Depends(admins_only), db: Session = Depends(get_db)):
    article = KBArticle()
    _apply_kb(article, body)
    db.add(article)
    db.commit()
    semantic_index.request_sync()
    return kb_dict(article)


@router.put("/kb/{article_id}")
def update_kb(article_id: int, body: KBArticleIn, _: StaffUser = Depends(admins_only),
              db: Session = Depends(get_db)):
    article = _manual_article_or_404(db, article_id)
    _apply_kb(article, body)
    db.commit()
    semantic_index.request_sync()
    return kb_dict(article)


@router.delete("/kb/{article_id}")
def delete_kb(article_id: int, _: StaffUser = Depends(admins_only), db: Session = Depends(get_db)):
    article = _manual_article_or_404(db, article_id)
    db.delete(article)
    db.commit()
    semantic_index.request_sync()
    return {"ok": True}


@router.get("/search/status")
def search_status(_: StaffUser = Depends(any_staff)):
    st = semantic_index.status
    return {"semantic_enabled": settings.semantic_enabled, "state": st.state, "message": st.message,
            "indexed_articles": st.indexed, "reranker": st.reranker, "embedding_model": settings.EMBEDDING_MODEL,
            "vector_store": settings.VECTOR_STORE, "reranker_model": settings.RERANKER_MODEL}


@router.post("/search/reindex")
def search_reindex(_: StaffUser = Depends(admins_only)):
    if not settings.semantic_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Semantic search is off (EMBEDDING_PROVIDER=none)")
    semantic_index.request_sync()
    return {"ok": True}


# ------------------------------------------------------------------ customers
@router.get("/customers")
def list_customers(_: StaffUser = Depends(admins_only), db: Session = Depends(get_db)):
    counts = dict(db.query(Ticket.customer_id, func.count(Ticket.id)).group_by(Ticket.customer_id).all())
    rows = db.query(Customer).order_by(Customer.created_at.desc()).all()
    return [{"id": c.id, "username": c.username, "name": c.name, "phone": c.phone,
             "ticket_count": counts.get(c.id, 0), "is_active": c.is_active,
             "created_at": iso(c.created_at)} for c in rows]


def _customer_or_404(db: Session, customer_id: str) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    return customer


@router.put("/customers/{customer_id}/password")
def reset_customer_password(customer_id: str, body: PasswordReset, _: StaffUser = Depends(admins_only),
                            db: Session = Depends(get_db)):
    customer = _customer_or_404(db, customer_id)
    customer.password_hash = hash_password(body.new_password)
    db.commit()
    return {"ok": True}


@router.put("/customers/{customer_id}/active")
def set_customer_active(customer_id: str, body: ActiveFlag, _: StaffUser = Depends(admins_only),
                        db: Session = Depends(get_db)):
    customer = _customer_or_404(db, customer_id)
    customer.is_active = body.is_active
    db.commit()
    return {"ok": True, "is_active": customer.is_active}


@router.delete("/customers/{customer_id}")
def delete_customer(customer_id: str, _: StaffUser = Depends(admins_only), db: Session = Depends(get_db)):
    customer = _customer_or_404(db, customer_id)
    if db.query(func.count(Ticket.id)).filter(Ticket.customer_id == customer.id).scalar():
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Customers with tickets cannot be deleted; disable the account instead")
    db.delete(customer)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ personas
def persona_full(p: Persona) -> dict:
    return {"id": p.id, "name": p.name, "role": p.role, "description": p.description,
            "tone_instructions_ar": p.tone_instructions_ar, "is_default": p.is_default,
            "verbosity": p.verbosity, "max_words": p.max_words}


@router.get("/personas")
def list_personas(_: StaffUser = Depends(admins_only), db: Session = Depends(get_db)):
    return [persona_full(p) for p in db.query(Persona).order_by(Persona.sort_order, Persona.name).all()]


@router.put("/personas/{persona_id}")
def update_persona(persona_id: str, body: PersonaUpdate, _: StaffUser = Depends(admins_only),
                   db: Session = Depends(get_db)):
    persona = db.get(Persona, persona_id)
    if persona is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Persona not found")
    persona.name = body.name
    persona.role = body.role or None
    persona.description = body.description or None
    persona.tone_instructions_ar = body.tone_instructions_ar
    # verbosity / max_words are kept unless the client sends new values
    if body.verbosity is not None:
        persona.verbosity = body.verbosity
    if body.max_words is not None:
        persona.max_words = body.max_words
    if body.is_default:
        db.query(Persona).filter(Persona.id != persona.id).update({Persona.is_default: False})
        persona.is_default = True
    elif persona.is_default:
        # exactly one default must always exist: it can only be moved by choosing another one
        persona.is_default = True
    db.commit()
    return persona_full(persona)


# ------------------------------------------------------------------ reset temporary data
@router.post("/reset")
def reset_temporary_data(_: StaffUser = Depends(admins_only), db: Session = Depends(get_db)):
    """Delete tickets, chats, calls, escalations and metrics. KB, personas, customers, staff are kept."""
    for model in (Escalation, TicketCall, TicketMessage, Ticket):
        db.query(model).delete(synchronize_session=False)
    db.commit()
    metrics.clear()
    agent.reset_cache()
    return {"ok": True}
