"""Knowledge-base documents: upload PDF / DOCX / TXT files (admins), list them (all staff), delete (admins)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import ADMIN_ROLES, require_staff
from app.models import Document, StaffUser, iso
from app.rag.semantic.index import semantic_index
from app.rag import ingestion as documents

router = APIRouter(prefix="/admin/documents", tags=["Documents"])

any_staff = require_staff()
admins_only = require_staff(*ADMIN_ROLES)


def document_dict(d: Document) -> dict:
    return {"id": d.id, "title": d.title, "filename": d.filename, "file_type": d.file_type,
            "size_bytes": d.size_bytes, "chunk_count": d.chunk_count, "product": d.product,
            "uploaded_by": d.uploaded_by, "created_at": iso(d.created_at)}


@router.get("")
def list_documents(_: StaffUser = Depends(any_staff), db: Session = Depends(get_db)):
    return [document_dict(d) for d in db.query(Document).order_by(Document.created_at.desc()).all()]


@router.post("", status_code=status.HTTP_201_CREATED)
def upload_document(file: UploadFile = File(...), product: Optional[str] = Form(None),
                    staff: StaffUser = Depends(admins_only), db: Session = Depends(get_db)):
    data = file.file.read(documents.MAX_UPLOAD_BYTES + 1)  # never read more than the limit into memory
    try:
        document = documents.ingest(db, file.filename or "", data, product, staff.username)
    except documents.DocumentError as exc:
        raise HTTPException(exc.status_code, str(exc))
    semantic_index.request_sync()
    return document_dict(document)


@router.delete("/{document_id}")
def delete_document(document_id: str, _: StaffUser = Depends(admins_only), db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    documents.delete_document(db, document)
    semantic_index.request_sync()
    return {"ok": True}
