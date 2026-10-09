"""SQLAlchemy models module alias - imports and re-exports everything from app.documents."""
from __future__ import annotations

from app.documents import (  # noqa: F401
    Base,
    Customer,
    Document,
    Escalation,
    KBArticle,
    KBEmbedding,
    Persona,
    StaffUser,
    Ticket,
    TicketCall,
    TicketMessage,
    as_utc,
    iso,
    new_id,
    utcnow,
)
