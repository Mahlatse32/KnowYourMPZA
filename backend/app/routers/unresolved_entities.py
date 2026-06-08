import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.politician import Politician
from app.models.politician_alias import PoliticianAlias
from app.models.unresolved_entity import UnresolvedEntity
from app.schemas.unresolved_entity import UnresolvedEntityRead, UnresolvedIgnoreRequest, UnresolvedResolveRequest

router = APIRouter(prefix="/unresolved-entities", tags=["unresolved entities"])


@router.get("", response_model=list[UnresolvedEntityRead])
def list_unresolved_entities(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[UnresolvedEntity]:
    stmt = select(UnresolvedEntity).order_by(UnresolvedEntity.created_at.desc()).limit(limit).offset(offset)
    if status:
        stmt = stmt.where(UnresolvedEntity.status == status.upper())
    return list(db.scalars(stmt))


@router.get("/{entity_id}", response_model=UnresolvedEntityRead)
def get_unresolved_entity(entity_id: uuid.UUID, db: Session = Depends(get_db)) -> UnresolvedEntity:
    entity = db.get(UnresolvedEntity, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Unresolved entity not found.")
    return entity


@router.post("/{entity_id}/resolve", response_model=UnresolvedEntityRead)
def resolve_unresolved_entity(
    entity_id: uuid.UUID,
    payload: UnresolvedResolveRequest,
    db: Session = Depends(get_db),
) -> UnresolvedEntity:
    entity = db.get(UnresolvedEntity, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Unresolved entity not found.")
    politician = db.get(Politician, payload.politician_id)
    if politician is None:
        raise HTTPException(status_code=404, detail="Politician not found.")
    entity.status = "RESOLVED"
    entity.resolved_politician_id = politician.id
    entity.resolved_at = datetime.now(UTC)
    entity.resolution_notes = payload.notes
    if payload.create_alias and entity.raw_value:
        alias = " ".join(entity.raw_value.split())
        existing = db.scalars(
            select(PoliticianAlias).where(PoliticianAlias.politician == politician, PoliticianAlias.alias == alias)
        ).first()
        if existing is None:
            db.add(
                PoliticianAlias(
                    politician=politician,
                    alias=alias,
                    alias_type=payload.alias_type or "SOURCE_VARIANT",
                    source_url=entity.source_url,
                )
            )
    db.commit()
    db.refresh(entity)
    return entity


@router.post("/{entity_id}/ignore", response_model=UnresolvedEntityRead)
def ignore_unresolved_entity(
    entity_id: uuid.UUID,
    payload: UnresolvedIgnoreRequest | None = None,
    db: Session = Depends(get_db),
) -> UnresolvedEntity:
    entity = db.get(UnresolvedEntity, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Unresolved entity not found.")
    entity.status = "IGNORED"
    entity.resolution_notes = payload.notes if payload else None
    db.commit()
    db.refresh(entity)
    return entity
