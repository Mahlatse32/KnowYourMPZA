from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.ingestion.people_assembly import create_slug
from app.main import app
from app.models.unresolved_entity import UnresolvedEntity
from sqlalchemy import select


client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_seed_ingestion_and_main_path():
    response = client.post("/ingest/seed")
    assert response.status_code == 200

    search = client.get("/search?name=malema")
    assert search.status_code == 200
    results = search.json()
    assert results
    politician_id = results[0]["id"]

    detail = client.get(f"/politicians/{politician_id}")
    assert detail.status_code == 200
    assert detail.json()["party"]["short_name"]

    committees = client.get(f"/politicians/{politician_id}/committees")
    assert committees.status_code == 200
    assert committees.json()
    assert committees.json()[0]["source_url"]

    documents = client.get(f"/politicians/{politician_id}/documents")
    assert documents.status_code == 200
    assert documents.json()
    assert documents.json()[0]["source_url"]

    paged = client.get("/politicians?limit=5&offset=0")
    assert paged.status_code == 200
    assert len(paged.json()) <= 5


def test_quality_summary():
    client.post("/ingest/seed")
    response = client.get("/quality/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["total_politicians"] >= 10
    assert "total_aliases" in body


def test_slug_creation():
    assert create_slug("Julius Sello Malema") == "julius-sello-malema"


def test_duplicate_seed_idempotency():
    first = client.post("/ingest/seed")
    second = client.post("/ingest/seed")
    assert first.status_code == 200
    assert second.status_code == 200
    assert client.get("/quality/summary").json()["total_politicians"] >= 10


def test_party_committee_document_and_ingestion_run_endpoints():
    client.post("/ingest/seed")

    parties = client.get("/parties")
    assert parties.status_code == 200
    party = parties.json()[0]
    assert client.get(f"/parties/{party['id']}").status_code == 200
    assert client.get(f"/parties/{party['id']}/politicians").status_code == 200

    committees = client.get("/committees")
    assert committees.status_code == 200
    committee = committees.json()[0]
    assert client.get(f"/committees/{committee['id']}").status_code == 200
    assert client.get(f"/committees/{committee['id']}/politicians").status_code == 200

    documents = client.get("/documents")
    assert documents.status_code == 200
    document = documents.json()[0]
    detail = client.get(f"/documents/{document['id']}")
    assert detail.status_code == 200
    assert "mentions" in detail.json()

    body = {"urls": ["https://pmg.org.za/committee-meeting/example-invalid/"]}
    response = client.post("/ingest/pmg-documents", json=body)
    assert response.status_code == 200
    runs = client.get("/ingestion/runs")
    assert runs.status_code == 200
    assert runs.json()
    run_id = runs.json()[0]["id"]
    assert client.get(f"/ingestion/runs/{run_id}").status_code == 200


def test_parliamentary_question_ingestion_and_browse(monkeypatch):
    client.post("/ingest/seed")
    politician_id = client.get("/search?name=malema").json()[0]["id"]
    url = "https://www.parliament.gov.za/question/test-malema-001"

    html = """
    <html><head><title>Question NW1</title></head><body>
      <h1>Written question about school infrastructure</h1>
      <p>Question Number: NW1</p>
      <p>Asked By: Julius Malema</p>
      <p>Department: Basic Education</p>
      <p>Minister: Minister of Basic Education</p>
      <p>Asked Date: 01 June 2026</p>
      <p>Answered Date: 07 June 2026</p>
      <p>Status: Answered</p>
      <p>Question: What schools require urgent repairs?</p>
      <p>Answer: The department supplied the list to Mr Malema.</p>
    </body></html>
    """
    monkeypatch.setattr("app.ingestion.parliament_questions.fetch_page", lambda _: html)

    response = client.post("/ingest/parliamentary-questions", json={"urls": [url]})
    assert response.status_code == 200
    assert response.json()["processed_count"] == 1

    second = client.post("/ingest/parliamentary-questions", json={"urls": [url]})
    assert second.status_code == 200
    assert second.json()["updated_count"] >= 1

    questions = client.get("/questions")
    assert questions.status_code == 200
    question = next(item for item in questions.json() if item["source_url"] == url)
    assert question["asked_by_name"] == "Julius Malema"
    assert question["politician"]["id"] == politician_id
    assert question["archive_path"]

    detail = client.get(f"/questions/{question['id']}")
    assert detail.status_code == 200
    assert detail.json()["mentions"]

    politician_questions = client.get(f"/politicians/{politician_id}/questions")
    assert politician_questions.status_code == 200
    assert any(item["source_url"] == url for item in politician_questions.json())

    quality = client.get("/quality/summary").json()
    assert "total_parliamentary_questions" in quality
    assert "total_question_mentions" in quality


def test_unresolved_question_asker_creates_unresolved_entity(monkeypatch):
    url = "https://www.parliament.gov.za/question/test-unresolved-001"
    html = """
    <html><body>
      <h1>Question from unresolved source text</h1>
      <p>Question Number: NW999</p>
      <p>Asked By: Unknown Future MP</p>
      <p>Department: Public Works</p>
      <p>Question: What work is planned?</p>
    </body></html>
    """
    monkeypatch.setattr("app.ingestion.parliament_questions.fetch_page", lambda _: html)

    response = client.post("/ingest/parliamentary-questions", json={"urls": [url]})
    assert response.status_code == 200
    assert response.json()["processed_count"] == 1

    question = next(item for item in client.get("/questions").json() if item["source_url"] == url)
    assert question["asked_by_name"] == "Unknown Future MP"
    assert question["politician"] is None

    with SessionLocal() as db:
        entity = db.scalars(
            select(UnresolvedEntity).where(
                UnresolvedEntity.source_url == url,
                UnresolvedEntity.raw_value == "Unknown Future MP",
                UnresolvedEntity.entity_type == "POLITICIAN",
            )
        ).first()
        assert entity is not None
