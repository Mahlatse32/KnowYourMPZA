import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.document import DocumentDetailRead, DocumentRead
from app.services.browse_service import get_document, list_documents

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=list[DocumentRead])
def documents(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    return list_documents(db, limit, offset)


@router.get("/{document_id}", response_model=DocumentDetailRead)
def document_detail(document_id: uuid.UUID, db: Session = Depends(get_db)):
    document = get_document(db, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document
