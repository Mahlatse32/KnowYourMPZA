import pytest
import importlib
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models.ai_answer import AiAnswer

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
    assert body["data_snapshot"]["ai_answer_format_version"] == 2


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
