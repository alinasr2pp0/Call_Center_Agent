'''SQLAlchemy 2.0 models (SQLite friendly: string UUID keys, UTC timestamps).'''

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, Float, LargeBinary, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite returns naive datetimes; everything we store is UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def iso(value: Optional[datetime]) -> Optional[str]:
    """ISO-8601 in UTC with a trailing Z so browsers parse it as UTC."""
    value = as_utc(value)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z" if value else None


class StaffUser(Base):
    __tablename__ = "staff_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="agent")  # superadmin | admin | agent
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[str] = mapped_column(String(32), index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    tickets: Mapped[List["Ticket"]] = relationship(back_populates="customer")


class Persona(Base):
    __tablename__ = "personas"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    tone_instructions_ar: Mapped[str] = mapped_column(Text, default="")
    verbosity: Mapped[str] = mapped_column(String(20), default="medium")
    max_words: Mapped[int] = mapped_column(Integer, default=120)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Document(Base):
    """An uploaded file (PDF / DOCX / TXT). Only its text is kept: it lives in ``KBArticle`` chunks."""
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(300))
    filename: Mapped[str] = mapped_column(String(300))
    file_type: Mapped[str] = mapped_column(String(10))  # pdf | docx | txt
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)  # sha256: the same file is stored once
    product: Mapped[str] = mapped_column(String(200), default="")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class KBArticle(Base):
    __tablename__ = "kb_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product: Mapped[str] = mapped_column(String(200), default="")
    ticket_type: Mapped[str] = mapped_column(String(200), default="")
    subject: Mapped[str] = mapped_column(String(500), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    resolution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="Open")
    priority: Mapped[str] = mapped_column(String(20), default="Medium")
    channel: Mapped[str] = mapped_column(String(50), default="Phone")
    # set only for chunks that come from an uploaded document (manual articles keep it NULL)
    document_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (Index("ix_tickets_customer_opened", "customer_id", "opened_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), index=True)
    persona_id: Mapped[Optional[str]] = mapped_column(ForeignKey("personas.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    # open | resolved_by_rag | resolved_confirmed | escalated
    category: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    resolution_attempts: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    used_web_search: Mapped[bool] = mapped_column(Boolean, default=False)
    initially_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    first_answer_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    customer: Mapped[Customer] = relationship(back_populates="tickets")
    messages: Mapped[List["TicketMessage"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", passive_deletes=True,
        order_by="TicketMessage.id")
    calls: Mapped[List["TicketCall"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", passive_deletes=True,
        order_by="TicketCall.id")
    escalations: Mapped[List["Escalation"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", passive_deletes=True,
        order_by="Escalation.id")


class TicketMessage(Base):
    __tablename__ = "ticket_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    sender: Mapped[str] = mapped_column(String(20))  # customer | agent | system
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    ticket: Mapped[Ticket] = relationship(back_populates="messages")


class TicketCall(Base):
    __tablename__ = "ticket_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="scheduled", index=True)
    # scheduled | in_progress | completed | no_answer | failed
    outcome: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # resolved_confirmed | escalated_to_agent | transferred_to_agent
    answered: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_call_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    dtmf: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    ticket: Mapped[Ticket] = relationship(back_populates="calls")


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    ticket: Mapped[Ticket] = relationship(back_populates="escalations")


class KBEmbedding(Base):
    """One embedding vector per knowledge-base article (used by the SQLite vector store)."""
    __tablename__ = "kb_embeddings"

    article_id: Mapped[int] = mapped_column(ForeignKey("kb_articles.id", ondelete="CASCADE"), primary_key=True)
    model: Mapped[str] = mapped_column(String(200))
    dim: Mapped[int] = mapped_column(Integer)
    text_hash: Mapped[str] = mapped_column(String(64))
    vector: Mapped[bytes] = mapped_column(LargeBinary)  # float32 little-endian, L2-normalised
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
