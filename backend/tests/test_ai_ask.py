import pytest
import importlib
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models.ai_answer import AiAnswer
from app.services.ai_service import _clean_parliament_question_text

importlib.import_module("app.models")


client = TestClient(app)


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestingSessionLocal() as db:
        yield db
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def _ingest_eskom_question(monkeypatch, db_session):
    client.post("/ingest/seed")
    url = "https://www.parliament.gov.za/question/test-ai-eskom-001"
    html = """
    <html><body>
      <h1>Written question reply NW-AI-1 â Eskom maintenance</h1>
      <p>Question Number: NW-AI-1</p>
      <p>Asked By: Julius Malema</p>
      <p>Department: Electricity</p>
      <p>Status: Answered</p>
      <p>Question: Which Eskom substations require urgent maintenance?</p>
      <p>Answer: The department supplied a schedule of Eskom maintenance work.</p>
    </body></html>
    """
    monkeypatch.setattr("app.ingestion.parliament_questions.fetch_page", lambda _: html)
    response = client.post("/ingest/parliamentary-questions", json={"urls": [url]})
    assert response.status_code == 200
    return url


def _ingest_multiple_eskom_questions(monkeypatch, db_session):
    client.post("/ingest/seed")
    pages = {
        "https://www.parliament.gov.za/question/test-ai-dlamini-eskom": """
        <html><body>
          <h1>Written question reply NW1025 - Eskom maintenance</h1>
          <p>Question Number: NW1025</p>
          <p>Asked By: Ms M Dlamini (EFF)</p>
          <p>Department: Water and Sanitation</p>
          <p>Status: Answered</p>
          <p>Question: Whether Eskom substations require urgent maintenance?</p>
          <p>Answer: The department supplied an Eskom maintenance schedule.</p>
        </body></html>
        """,
        "https://www.parliament.gov.za/question/test-ai-tito-eskom": """
        <html><body>
          <h1>Written question reply NW1661 - Eskom school connection</h1>
          <p>Question Number: NW1661</p>
          <p>Asked By: Mrs L F Tito (EFF)</p>
          <p>Department: Basic Education</p>
          <p>Status: Answered</p>
          <p>Question: Whether Eskom has connected schools to electricity?</p>
          <p>Answer: The department reported on school electricity connections.</p>
        </body></html>
        """,
    }
    monkeypatch.setattr("app.ingestion.parliament_questions.fetch_page", lambda url: pages[url])
    response = client.post("/ingest/parliamentary-questions", json={"urls": list(pages)})
    assert response.status_code == 200


def test_ai_ask_returns_source_backed_answer_without_openai_key(monkeypatch, db_session):
    monkeypatch.setattr("app.services.ai_service.settings.openai_api_key", "")
    source_url = _ingest_eskom_question(monkeypatch, db_session)

    response = client.post("/ai/ask", json={"question": "Which MPs asked questions about Eskom?"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "questions"
    assert body["model_used"] == "deterministic-source-summary"
    assert body["cached"] is False
    assert "Eskom" in body["answer"]
    assert "The records include questions from Julius Malema" in body["answer"]
    assert "Relevant source-backed records:" in body["answer"]
    assert "NATIONAL ASSEMBLY QUESTION" not in body["answer"]
    assert "â" not in body["answer"]
    assert any(source["source_url"] == source_url for source in body["sources"])
    assert any(source["asked_by"] == "Julius Malema" for source in body["sources"])
    assert body["data_snapshot"]["parliamentary_questions"] >= 1
    assert body["data_snapshot"]["ai_answer_format_version"] == 5


def test_ai_ask_filters_questions_by_named_mp_and_topic(monkeypatch, db_session):
    monkeypatch.setattr("app.services.ai_service.settings.openai_api_key", "")
    _ingest_multiple_eskom_questions(monkeypatch, db_session)

    response = client.post("/ai/ask", json={"question": "what did Ms M Dlamini (EFF) ask about eskom?"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "questions"
    assert "where Ms M Dlamini (EFF) asked about Eskom" in body["answer"]
    assert "Ms M Dlamini (EFF)" in body["answer"]
    assert "Mrs L F Tito" not in body["answer"]
    assert all("Dlamini" in f"{source.get('asked_by')} {source.get('excerpt')}" for source in body["sources"])
    assert all("Tito" not in f"{source.get('asked_by')} {source.get('excerpt')}" for source in body["sources"])
    assert all("Eskom" in f"{source['title']} {source.get('excerpt')}" for source in body["sources"])
    assert body["data_snapshot"]["ai_answer_format_version"] == 5


def test_ai_question_evidence_text_is_cleaned_before_answering():
    raw = (
        "NATIONAL ASSEMBLY QUESTION 1025 NW1153E NATIONAL ASSEMBLY FOR WRITTEN REPLY "
        "QUESTION NO 1025 DATE OF PUBLICATION IN INTERNAL QUESTION PAPER: 06 MARCH 2026 "
        "1025. Ms M Dlamini (EFF) to ask the Minister of Water and Sanitation: "
        "Whether Eskom substations require urgent maintenance?"
    )

    cleaned = _clean_parliament_question_text(raw, "Ms M Dlamini (EFF)")

    assert cleaned is not None
    assert cleaned.startswith("asked the Minister of Water and Sanitation")
    assert "NATIONAL ASSEMBLY QUESTION" not in cleaned
    assert "to ask the Ministe..." not in cleaned


def test_ai_ask_reuses_saved_answer_when_snapshot_is_unchanged(monkeypatch, db_session):
    monkeypatch.setattr("app.services.ai_service.settings.openai_api_key", "")
    _ingest_eskom_question(monkeypatch, db_session)

    first = client.post("/ai/ask", json={"question": "Which MPs asked questions about Eskom?"})
    second = client.post("/ai/ask", json={"question": "Which MPs asked questions about Eskom?"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["cached"] is True
    count = db_session.scalar(
        select(func.count()).select_from(AiAnswer).where(AiAnswer.normalized_question == "which mps asked questions about eskom?")
    )
    assert count == 1


def test_ai_ask_refresh_regenerates_saved_answer(monkeypatch, db_session):
    monkeypatch.setattr("app.services.ai_service.settings.openai_api_key", "")
    _ingest_eskom_question(monkeypatch, db_session)

    first = client.post("/ai/ask", json={"question": "Which MPs asked questions about Eskom?"})
    refreshed = client.post("/ai/ask", json={"question": "Which MPs asked questions about Eskom?", "refresh": True})

    assert first.status_code == 200
    assert refreshed.status_code == 200
    assert first.json()["id"] == refreshed.json()["id"]
    assert refreshed.json()["cached"] is False
