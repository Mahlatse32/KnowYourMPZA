import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models.parliamentary_question import ParliamentaryQuestion
from app.models.politician import Politician
from app.models.question_mention import QuestionMention
from app.schemas.question import ParliamentaryQuestionDetailResponse, ParliamentaryQuestionResponse

router = APIRouter(tags=["questions"])


@router.get("/questions", response_model=list[ParliamentaryQuestionResponse])
def list_questions(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    politician_id: uuid.UUID | None = None,
    department: str | None = None,
    minister: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
) -> list[ParliamentaryQuestion]:
    statement = (
        select(ParliamentaryQuestion)
        .options(
            joinedload(ParliamentaryQuestion.politician).joinedload(Politician.party),
            joinedload(ParliamentaryQuestion.source),
        )
        .order_by(ParliamentaryQuestion.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if politician_id:
        statement = statement.where(ParliamentaryQuestion.politician_id == politician_id)
    if department:
        statement = statement.where(ParliamentaryQuestion.department == department)
    if minister:
        statement = statement.where(ParliamentaryQuestion.minister == minister)
    if status:
        statement = statement.where(ParliamentaryQuestion.status == status)
    return list(db.scalars(statement).unique())


@router.get("/questions/{question_id}", response_model=ParliamentaryQuestionDetailResponse)
def get_question(question_id: uuid.UUID, db: Session = Depends(get_db)) -> ParliamentaryQuestion:
    question = db.scalars(
        select(ParliamentaryQuestion)
        .options(
            joinedload(ParliamentaryQuestion.politician).joinedload(Politician.party),
            joinedload(ParliamentaryQuestion.source),
            joinedload(ParliamentaryQuestion.mentions)
            .joinedload(QuestionMention.politician)
            .joinedload(Politician.party),
        )
        .where(ParliamentaryQuestion.id == question_id)
    ).unique().first()
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found.")
    return question


@router.get("/politicians/{politician_id}/questions", response_model=list[ParliamentaryQuestionResponse])
def get_politician_questions(
    politician_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[ParliamentaryQuestion]:
    politician = db.scalars(select(Politician).where(Politician.id == politician_id)).first()
    if politician is None:
        raise HTTPException(status_code=404, detail="Politician not found.")
    statement = (
        select(ParliamentaryQuestion)
        .options(
            joinedload(ParliamentaryQuestion.politician).joinedload(Politician.party),
            joinedload(ParliamentaryQuestion.source),
        )
        .where(ParliamentaryQuestion.politician_id == politician_id)
        .order_by(ParliamentaryQuestion.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(statement).unique())
