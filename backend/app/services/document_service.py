from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.document import Document


def list_documents(db: Session) -> list[Document]:
    statement = select(Document).options(joinedload(Document.source)).order_by(Document.publication_date.desc().nullslast())
    return list(db.scalars(statement).unique())
