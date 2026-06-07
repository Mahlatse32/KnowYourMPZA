import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.models.committee_membership import CommitteeMembership
from app.models.document import Document
from app.models.document_mention import DocumentMention
from app.models.politician_alias import PoliticianAlias
from app.models.politician import Politician


def list_politicians(db: Session, limit: int = 50, offset: int = 0) -> list[Politician]:
    statement = (
        select(Politician)
        .options(joinedload(Politician.party))
        .order_by(Politician.display_name)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(statement).unique())


def get_politician(db: Session, politician_id: uuid.UUID) -> Politician | None:
    statement = (
        select(Politician)
        .options(joinedload(Politician.party), joinedload(Politician.aliases))
        .where(Politician.id == politician_id)
    )
    return db.scalars(statement).first()


def search_politicians(db: Session, name: str) -> list[Politician]:
    pattern = f"%{name.strip()}%"
    statement = (
        select(Politician)
        .outerjoin(PoliticianAlias)
        .options(joinedload(Politician.party))
        .where(
            or_(
                Politician.full_name.ilike(pattern),
                Politician.display_name.ilike(pattern),
                Politician.slug.ilike(pattern),
                PoliticianAlias.alias.ilike(pattern),
            )
        )
        .order_by(Politician.display_name)
    )
    return list(db.scalars(statement).unique())


def list_politician_committee_memberships(db: Session, politician_id: uuid.UUID) -> list[CommitteeMembership]:
    statement = (
        select(CommitteeMembership)
        .options(joinedload(CommitteeMembership.committee))
        .where(CommitteeMembership.politician_id == politician_id)
        .order_by(CommitteeMembership.role, CommitteeMembership.id)
    )
    return list(db.scalars(statement).unique())


def list_politician_document_mentions(db: Session, politician_id: uuid.UUID, limit: int = 50, offset: int = 0) -> list[DocumentMention]:
    statement = (
        select(DocumentMention)
        .options(joinedload(DocumentMention.document).joinedload(Document.source))
        .where(DocumentMention.politician_id == politician_id)
        .order_by(DocumentMention.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(statement).unique())
