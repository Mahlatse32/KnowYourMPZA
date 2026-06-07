from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.committee import Committee
from app.models.committee_membership import CommitteeMembership
from app.models.document import Document
from app.models.document_mention import DocumentMention
from app.models.party import Party
from app.models.politician import Politician


def list_committees(db: Session, limit: int = 50, offset: int = 0) -> list[Committee]:
    return list(db.scalars(select(Committee).order_by(Committee.name).limit(limit).offset(offset)))


def get_committee(db: Session, committee_id: UUID) -> Committee | None:
    return db.get(Committee, committee_id)


def committee_politicians(db: Session, committee_id: UUID, limit: int = 50, offset: int = 0) -> list[Politician]:
    statement = (
        select(Politician)
        .join(CommitteeMembership)
        .options(joinedload(Politician.party))
        .where(CommitteeMembership.committee_id == committee_id)
        .order_by(Politician.display_name)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(statement).unique())


def list_documents(db: Session, limit: int = 50, offset: int = 0) -> list[Document]:
    statement = (
        select(Document)
        .options(joinedload(Document.source))
        .order_by(Document.publication_date.desc().nullslast(), Document.title)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(statement).unique())


def get_document(db: Session, document_id: UUID) -> Document | None:
    return db.scalars(
        select(Document)
        .options(
            joinedload(Document.source),
            joinedload(Document.mentions).joinedload(DocumentMention.politician).joinedload(Politician.party),
        )
        .where(Document.id == document_id)
    ).unique().first()


def list_parties(db: Session, limit: int = 50, offset: int = 0) -> list[Party]:
    return list(db.scalars(select(Party).order_by(Party.name).limit(limit).offset(offset)))


def get_party(db: Session, party_id: UUID) -> Party | None:
    return db.get(Party, party_id)


def party_politicians(db: Session, party_id: UUID, limit: int = 50, offset: int = 0) -> list[Politician]:
    statement = (
        select(Politician)
        .options(joinedload(Politician.party))
        .where(Politician.party_id == party_id)
        .order_by(Politician.display_name)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(statement).unique())
