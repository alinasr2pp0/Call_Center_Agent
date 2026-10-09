"""Staff management (superadmin only)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.database import get_db
from app.deps import require_staff
from app.models import StaffUser, iso
from app.schemas import StaffCreate, StaffRoleUpdate

router = APIRouter(prefix="/staff", tags=["Staff"])


def staff_dict(s: StaffUser) -> dict:
    return {"id": s.id, "username": s.username, "role": s.role, "is_active": s.is_active,
            "created_at": iso(s.created_at)}


def _get_manageable(db: Session, staff_id: str) -> StaffUser:
    target = db.get(StaffUser, staff_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Staff member not found")
    if target.role == "superadmin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The superadmin account cannot be changed")
    return target


@router.get("")
def list_staff(_: StaffUser = Depends(require_staff("superadmin")), db: Session = Depends(get_db)):
    return [staff_dict(s) for s in db.query(StaffUser).order_by(StaffUser.created_at).all()]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_staff(body: StaffCreate, _: StaffUser = Depends(require_staff("superadmin")),
                 db: Session = Depends(get_db)):
    if db.query(StaffUser.id).filter(func.lower(StaffUser.username) == body.username.lower()).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists")
    staff = StaffUser(username=body.username, password_hash=hash_password(body.password), role=body.role)
    db.add(staff)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists")
    return staff_dict(staff)


@router.put("/{staff_id}/role")
def change_role(staff_id: str, body: StaffRoleUpdate, _: StaffUser = Depends(require_staff("superadmin")),
                db: Session = Depends(get_db)):
    target = _get_manageable(db, staff_id)
    target.role = body.role
    db.commit()
    return staff_dict(target)


@router.delete("/{staff_id}")
def delete_staff(staff_id: str, _: StaffUser = Depends(require_staff("superadmin")),
                 db: Session = Depends(get_db)):
    target = _get_manageable(db, staff_id)
    db.delete(target)
    db.commit()
    return {"ok": True}
