from datetime import date

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.ingestion.parliament_question_discovery import question_metadata_from_record
from app.ingestion.parliament_questions import (
    _apply_discovery_metadata,
    _title_is_url_derived,
    ingest_parliamentary_question_urls,
)
from app.main import app
from app.models.parliamentary_question import ParliamentaryQuestion


client = TestClient(app)


def _record(**overrides) -> dict:
    base = {
        "name": "RNW1763-2026-06-25.pdf",
        "date": "2026-06-25",
        "type": "EXE_RQ_NA",
        "file_location": "exe_rq_na/01pv5mf2a3rzop4au35nbj4zsnqkevny6w.pdf",
    }
    base.update(overrides)
    return base


def test_metadata_from_record_extracts_number_date_and_reply_status():
    metadata = question_metadata_from_record(_record())
    assert metadata["question_number"] == "NW1763"
    assert metadata["answered_date"] == date(2026, 6, 25)
    assert metadata["status"] == "ANSWERED"
    assert "NW1763" in metadata["title"]
    assert "National Assembly" in metadata["title"]


def test_metadata_rejects_corrupt_dates_but_recovers_from_filename():
    # The docsjson date field sometimes carries a question number ("5127-10-10").
    metadata = question_metadata_from_record(
        _record(name="RNW5127-10-10.pdf", date="5127-10-10")
    )
    assert "answered_date" not in metadata
    assert metadata["question_number"] == "NW5127"

    # A valid full date embedded in the filename is recovered.
    metadata = question_metadata_from_record(
        _record(name="RNW1763-2026-06-25.pdf", date="3206-02-26")
    )
    assert metadata["answered_date"] == date(2026, 6, 25)


def test_metadata_degrades_to_filename_stem_when_nothing_parses():
    metadata = question_metadata_from_record(
        _record(name="oddly-named-document.pdf", date="not-a-date", type="UNKNOWN_TYPE")
    )
    assert metadata.get("title") == "oddly-named-document"
    assert "question_number" not in metadata
    assert "asked_date" not in metadata
    assert "answered_date" not in metadata
    assert "status" not in metadata


def test_question_paper_dates_map_to_asked_date_without_status():
    metadata = question_metadata_from_record(
        _record(name="QUEST_PAP-2026-05-01.pdf", date="2026-05-01", type="QUEST_PAP")
    )
    assert metadata["asked_date"] == date(2026, 5, 1)
    assert "answered_date" not in metadata
    assert "status" not in metadata


def test_apply_metadata_prefers_document_values_over_metadata():
    parsed = {
        "title": "Written question about school infrastructure",
        "question_number": "NW999",
        "asked_date": date(2026, 1, 1),
        "answered_date": None,
        "status": "ANSWERED",
        "source_url": "https://www.parliament.gov.za/x/doc.pdf",
        "parse_notes": None,
    }
    _apply_discovery_metadata(
        parsed,
        {
            "title": "Written question reply NW1763 (National Assembly)",
            "question_number": "NW1763",
            "answered_date": date(2026, 6, 25),
            "status": "ANSWERED",
        },
    )
    # Document-derived title/number/status survive; only the missing
    # answered_date is filled.
    assert parsed["title"] == "Written question about school infrastructure"
    assert parsed["question_number"] == "NW999"
    assert parsed["answered_date"] == date(2026, 6, 25)
    assert "docsjson" in parsed["parse_notes"]


def test_apply_metadata_replaces_url_derived_titles():
    url = "https://www.parliament.gov.za/storage/app/media/Docs/exe_rq_na/01pv5mf2xyz.pdf"
    parsed = {
        "title": "01pv5mf2xyz",
        "question_number": None,
        "asked_date": None,
        "answered_date": None,
        "status": "UNANSWERED",
        "source_url": url,
        "parse_notes": None,
    }
    _apply_discovery_metadata(
        parsed,
        {
            "title": "Written question reply NW1763 (National Assembly) — 2026-06-25",
            "question_number": "NW1763",
            "answered_date": date(2026, 6, 25),
            "status": "ANSWERED",
        },
    )
    assert parsed["title"].startswith("Written question reply NW1763")
    assert parsed["question_number"] == "NW1763"
    assert parsed["status"] == "ANSWERED"


def test_title_is_url_derived_detection():
    url = "https://www.parliament.gov.za/storage/app/media/Docs/exe_rq_na/01pv5mf2xyz.pdf"
    assert _title_is_url_derived(None, url)
    assert _title_is_url_derived("01pv5mf2xyz", url)
    assert _title_is_url_derived(f"Parliamentary question: {url}", url)
    assert not _title_is_url_derived("Real document heading", url)


def test_ingest_applies_metadata_end_to_end(monkeypatch, tmp_path):
    url = f"https://www.parliament.gov.za/storage/app/media/Docs/exe_rq_na/e2e-{uuid.uuid4().hex}.pdf"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("app.ingestion.parliament_questions.download_file", lambda _: b"%PDF-1.4\n")
    monkeypatch.setattr(
        "app.ingestion.parliament_questions.extract_pdf_text",
        lambda _: "Reply text without any labelled fields",
    )

    with SessionLocal() as db:
        summary = ingest_parliamentary_question_urls(
            db,
            [url],
            metadata_by_url={
                url: {
                    "title": "Written question reply NW42 (National Assembly) — 2026-06-20",
                    "question_number": "NW42",
                    "answered_date": date(2026, 6, 20),
                    "status": "ANSWERED",
                }
            },
        )
        assert summary["created_count"] == 1
        question = db.scalars(
            select(ParliamentaryQuestion).where(ParliamentaryQuestion.source_url == url)
        ).one()
        assert question.title.startswith("Written question reply NW42")
        assert question.question_number == "NW42"
        assert question.answered_date == date(2026, 6, 20)
        assert question.status == "ANSWERED"
        assert "docsjson" in (question.parse_notes or "")


def test_ingest_without_metadata_still_works(monkeypatch, tmp_path):
    url = f"https://www.parliament.gov.za/storage/app/media/Docs/exe_rq_na/nometa-{uuid.uuid4().hex}.pdf"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("app.ingestion.parliament_questions.download_file", lambda _: b"%PDF-1.4\n")
    monkeypatch.setattr(
        "app.ingestion.parliament_questions.extract_pdf_text",
        lambda _: "Reply text without any labelled fields",
    )

    with SessionLocal() as db:
        summary = ingest_parliamentary_question_urls(db, [url])
        assert summary["created_count"] == 1
