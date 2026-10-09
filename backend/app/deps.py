"""FastAPI dependencies: authentication and role checks."""
from __future__ import annotations

from typing import Callable, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.database import get_db
from app.models import Customer, StaffUser

bearer_scheme = HTTPBearer(auto_error=False)

STAFF_ROLES = ("superadmin", "admin", "agent")
ADMIN_ROLES = ("superadmin", "admin")


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


def _payload(credentials: Optional[HTTPAuthorizationCredentials], kind: str) -> dict:
    if credentials is None or not credentials.credentials:
        raise _unauthorized()
    payload = decode_access_token(credentials.credentials)
    if not payload or payload.get("kind") != kind or not payload.get("sub"):
        raise _unauthorized("Invalid or expired token")
    return payload


def get_current_staff(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> StaffUser:
    payload = _payload(credentials, "staff")
    staff = db.get(StaffUser, payload["sub"])
    if staff is None or not staff.is_active:
        raise _unauthorized("Account not found or disabled")
    return staff


def require_staff(*roles: str) -> Callable[..., StaffUser]:
    allowed = roles or STAFF_ROLES

    def dependency(staff: StaffUser = Depends(get_current_staff)) -> StaffUser:
        if staff.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission for this action")
        return staff

    return dependency


def get_current_customer(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Customer:
    payload = _payload(credentials, "customer")
    customer = db.get(Customer, payload["sub"])
    if customer is None:
        raise _unauthorized("Account not found")
    if not customer.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is disabled")
    return customer


def client_key(request: Request, username: str, scope: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{scope}:{host}:{username.strip().lower()}"
