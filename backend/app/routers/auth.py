"""Staff login (admin dashboard) and customer sign-up/login (customer portal)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import (burn_password_check, create_access_token, hash_password, login_limiter,
                               verify_password)
from app.database import get_db
from app.deps import client_key, get_current_customer, get_current_staff
from app.models import Customer, StaffUser, Ticket, TicketCall, iso
from app.schemas import CustomerLogin, CustomerSignup, LoginRequest

router = APIRouter()

TOO_MANY = "Too many failed attempts, try again in a few minutes"


# ------------------------------------------------------------------ staff
@router.post("/auth/login", tags=["Staff"])
def staff_login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    key = client_key(request, body.username, "staff")
    if login_limiter.blocked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY)
    staff = db.query(StaffUser).filter(func.lower(StaffUser.username) == body.username.lower()).first()
    if staff is None:
        burn_password_check(body.password)
    if staff is None or not staff.is_active or not verify_password(body.password, staff.password_hash):
        login_limiter.fail(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    login_limiter.reset(key)
    token = create_access_token(staff.id, "staff", {"role": staff.role})
    return {"access_token": token, "token_type": "bearer", "role": staff.role, "username": staff.username}


@router.get("/auth/me", tags=["Staff"])
def staff_me(staff: StaffUser = Depends(get_current_staff)):
    return {"id": staff.id, "username": staff.username, "role": staff.role}


# ------------------------------------------------------------------ customers
def _customer_token(customer: Customer) -> dict:
    return {
        "access_token": create_access_token(customer.id, "customer"),
        "token_type": "bearer",
        "username": customer.username,
        "name": customer.name,
    }


@router.post("/customer-auth/signup", tags=["Customer"])
def customer_signup(body: CustomerSignup, db: Session = Depends(get_db)):
    exists = db.query(Customer.id).filter(func.lower(Customer.username) == body.username.lower()).first()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken")
    customer = Customer(username=body.username, name=body.name or None, phone=body.phone,
                        password_hash=hash_password(body.password))
    db.add(customer)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken")
    return _customer_token(customer)


@router.post("/customer-auth/login", tags=["Customer"])
def customer_login(body: CustomerLogin, request: Request, db: Session = Depends(get_db)):
    key = client_key(request, body.username, "customer")
    if login_limiter.blocked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY)
    customer = db.query(Customer).filter(func.lower(Customer.username) == body.username.lower()).first()
    if customer is None:
        burn_password_check(body.password)
    if customer is None or not verify_password(body.password, customer.password_hash):
        login_limiter.fail(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    if not customer.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is disabled")
    login_limiter.reset(key)
    return _customer_token(customer)


@router.get("/customer-auth/my/tickets", tags=["Customer"])
def my_tickets(customer: Customer = Depends(get_current_customer), db: Session = Depends(get_db)):
    rows = (db.query(Ticket).filter(Ticket.customer_id == customer.id)
            .order_by(Ticket.opened_at.desc()).limit(200).all())
    return [{"id": t.id, "status": t.status, "category": t.category, "opened_at": iso(t.opened_at)} for t in rows]


@router.get("/customer-auth/my/tickets/{ticket_id}", tags=["Customer"])
def my_ticket_detail(ticket_id: str, customer: Customer = Depends(get_current_customer),
                     db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id, Ticket.customer_id == customer.id).first()
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    return {
        "ticket": {"id": ticket.id, "status": ticket.status, "category": ticket.category,
                   "opened_at": iso(ticket.opened_at)},
        "messages": [{"sender": m.sender, "content": m.content, "created_at": iso(m.created_at)}
                     for m in ticket.messages],
        "calls": [call_dict(c) for c in ticket.calls if c.status != "scheduled"],
    }


def call_dict(call: TicketCall) -> dict:
    return {"id": call.id, "attempt": call.attempt, "status": call.status, "outcome": call.outcome,
            "duration_seconds": call.duration_seconds}
