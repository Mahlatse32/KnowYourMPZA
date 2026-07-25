from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.ai import AiAskRequest, AiAskResponse
from app.services.ai_service import answer_question, response_generated_at

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/ask", response_model=AiAskResponse)
def ask_ai(request: AiAskRequest, db: Session = Depends(get_db)) -> AiAskResponse:
    answer, cached = answer_question(db, request.question, refresh=request.refresh)
    return AiAskResponse(
        id=answer.id,
        question=answer.question,
        answer=answer.answer,
        intent=answer.intent,
        sources=answer.sources,
        coverage_notice=answer.coverage_notice or "",
        data_snapshot=answer.data_snapshot,
        model_used=answer.model_used,
        cached=cached,
        generated_at=response_generated_at(answer),
    )
