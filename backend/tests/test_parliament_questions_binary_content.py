import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.ingestion.parliament_questions import _is_binary_content
from app.main import app
from app.models.parliamentary_question import ParliamentaryQuestion


client = TestClient(app)

XLSX_LIKE_BODY = (
    "PK\x03\x04\x14\x00\x06\x00\x08\x00\x00\x00!\x00"
    + "\x00" * 32
    + "[Content_Types].xml binary payload"
)


def test_binary_content_detection():
    assert _is_binary_content(XLSX_LIKE_BODY)
    assert _is_binary_content("\xd0\xcf\x11\xe0" + "\x00" * 16 + "legacy .doc body")
    assert not _is_binary_content("<html><body>Question: text</body></html>")
    # A single stray NUL is not a binary document; it is sanitized instead.
    assert not _is_binary_content("<html>\x00broken</html>")


def test_xlsx_body_creates_failed_parse_record_without_nul_bytes(monkeypatch, tmp_path):
    url = f"https://www.parliament.gov.za/storage/app/media/Docs/exe_rq_na/binary-test-{uuid.uuid4().hex}.xlsx"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("app.ingestion.parliament_questions.fetch_page", lambda _: XLSX_LIKE_BODY)

    response = client.post("/ingest/parliamentary-questions", json={"urls": [url]})
    assert response.status_code == 200
    assert response.json()["processed_count"] == 1
    assert response.json()["created_count"] == 1
    assert response.json()["failed_count"] == 0

    with SessionLocal() as db:
        question = db.scalars(
            select(ParliamentaryQuestion).where(ParliamentaryQuestion.source_url == url)
        ).one()
        assert question.parse_status == "FAILED"
        assert question.source_file_type == "XLSX"
        assert question.question_text is None
        assert question.extracted_text_available is False
        assert question.archive_path
        for value in (question.title, question.parse_notes, question.status):
            assert value is None or "\x00" not in value

    # The record now exists, so the new-record-first backfill queue advances
    # instead of retrying the same poison URL forever.
    second = client.post("/ingest/parliamentary-questions", json={"urls": [url]})
    assert second.status_code == 200
    assert second.json()["updated_count"] == 1
    assert second.json()["failed_count"] == 0


def test_nul_bytes_in_extracted_text_are_stripped_before_upsert(monkeypatch, tmp_path):
    url = f"https://www.parliament.gov.za/question/nul-in-text-{uuid.uuid4().hex}"
    html = (
        "<html><body><h1>Question NW77</h1>"
        "<p>Question: What hap\x00pened to the budget?</p>"
        "</body></html>"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("app.ingestion.parliament_questions.fetch_page", lambda _: html)

    response = client.post("/ingest/parliamentary-questions", json={"urls": [url]})
    assert response.status_code == 200
    assert response.json()["processed_count"] == 1

    with SessionLocal() as db:
        question = db.scalars(
            select(ParliamentaryQuestion).where(ParliamentaryQuestion.source_url == url)
        ).one()
        assert question.question_text
        assert "\x00" not in question.question_text
        assert "happened" in question.question_text
