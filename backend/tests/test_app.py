from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.ingestion.parliament_question_discovery import urls_from_listing
from app.ingestion.pdf_utils import archive_pdf, extract_pdf_text, is_pdf_url
from app.ingestion.people_assembly import (
    create_slug,
    discover_people_assembly_urls_from_listing,
    normalize_committee_name,
    normalize_party_name,
    normalize_people_assembly_url,
)
from app.main import app
from app.models.committee_membership import CommitteeMembership
from app.models.politician_alias import PoliticianAlias
from app.models.unresolved_entity import UnresolvedEntity
from app.services.ingestion_service import ingest_people_assembly_committees, ingest_people_assembly_profiles
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


def test_people_assembly_url_and_listing_discovery(monkeypatch):
    html = """
    <html><body>
      <a href="/person/julius-sello-malema/">Julius Malema</a>
      <a href="https://www.pa.org.za/person/example-mp/?utm=ignored">Example MP</a>
      <a href="/person/all/">All people</a>
    </body></html>
    """
    monkeypatch.setattr("app.ingestion.people_assembly.fetch_page", lambda _: html)

    assert normalize_people_assembly_url("https://www.pa.org.za/person/example-mp?utm=1") == "https://www.pa.org.za/person/example-mp/"
    urls = discover_people_assembly_urls_from_listing("https://www.pa.org.za/position/member/parliament/")
    assert urls == [
        "https://www.pa.org.za/person/example-mp/",
        "https://www.pa.org.za/person/julius-sello-malema/",
    ]


def test_party_and_committee_normalization():
    assert normalize_party_name(" African National Congress ( ANC ) ")[1] == "ANC"
    assert normalize_party_name("FF+")[1] == "FF Plus"
    assert normalize_committee_name("Portfolio Committee on  Health,,") == "Health"


def test_duplicate_seed_idempotency():
    first = client.post("/ingest/seed")
    second = client.post("/ingest/seed")
    assert first.status_code == 200
    assert second.status_code == 200
    assert client.get("/quality/summary").json()["total_politicians"] >= 10


def test_people_assembly_profile_upsert_idempotency(monkeypatch):
    url = "https://www.pa.org.za/person/coverage-test-mp/"
    html = """
    <html><head>
      <meta property="profile:first_name" content="Coverage">
      <meta property="profile:last_name" content="Tester">
    </head><body>
      <h1>Coverage Tester</h1>
      <div class="mp-block"><div class="mp-block__title">Political Party</div><a>Democratic Alliance (DA)</a></div>
      <div class="current-mp-positions">
        <div class="text-link"><div class="text-link__text">Member at <a href="/committee/test-committee/">Portfolio Committee on Testing</a></div></div>
      </div>
      Member of the National Assembly
    </body></html>
    """
    monkeypatch.setattr("app.services.ingestion_service.fetch_people_assembly_page", lambda _: html)
    with SessionLocal() as db:
        first = ingest_people_assembly_profiles(db, [url])
        second = ingest_people_assembly_profiles(db, [url])
        politicians = list(db.scalars(select(UnresolvedEntity).where(UnresolvedEntity.source_url == url)))
    assert first["processed_count"] == 1
    assert second["updated_count"] >= 1
    assert politicians == []


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


def test_committee_ingestion_idempotency_and_unresolved_capture(monkeypatch):
    client.post("/ingest/seed")
    url = "https://www.pa.org.za/committee/coverage-committee/"
    html = """
    <html><body>
      <h1>Portfolio Committee on Coverage</h1>
      <ul>
        <li>Chairperson <a href="/person/julius-sello-malema/">Julius Malema</a></li>
        <li>Member <a href="/person/unknown-coverage-person/">Unknown Coverage Person</a></li>
      </ul>
    </body></html>
    """
    monkeypatch.setattr("app.services.ingestion_service.fetch_people_assembly_page", lambda _: html)
    with SessionLocal() as db:
        first = ingest_people_assembly_committees(db, [url])
        second = ingest_people_assembly_committees(db, [url])
        unresolved = db.scalars(
            select(UnresolvedEntity).where(UnresolvedEntity.raw_value == "Unknown Coverage Person", UnresolvedEntity.status == "OPEN")
        ).first()
        memberships = list(db.scalars(select(CommitteeMembership).where(CommitteeMembership.source_url == url)))
    assert first["processed_count"] == 1
    assert second["processed_count"] == 1
    assert unresolved is not None
    assert len(memberships) == 1


def test_unresolved_entity_resolve_endpoint_creates_alias():
    client.post("/ingest/seed")
    politician_id = client.get("/search?name=malema").json()[0]["id"]
    with SessionLocal() as db:
        entity = UnresolvedEntity(
            source_name="test",
            source_url="https://example.test/unresolved",
            raw_value="Commander Malema",
            entity_type="POLITICIAN",
            status="OPEN",
        )
        db.add(entity)
        db.commit()
        entity_id = entity.id
    response = client.post(
        f"/unresolved-entities/{entity_id}/resolve",
        json={"politician_id": politician_id, "create_alias": True, "alias_type": "SOURCE_VARIANT", "notes": "test"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "RESOLVED"
    with SessionLocal() as db:
        alias = db.scalars(select(PoliticianAlias).where(PoliticianAlias.alias == "Commander Malema")).first()
        assert alias is not None


def test_quality_issues_endpoint():
    client.post("/ingest/seed")
    response = client.get("/quality/issues")
    assert response.status_code == 200
    body = response.json()
    assert "active_politicians_without_committees" in body
    assert "unresolved_entities_open" in body


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

    questions = client.get("/questions?limit=500")
    assert questions.status_code == 200
    question = next(item for item in questions.json() if item["source_url"] == url)
    assert question["asked_by_name"] == "Julius Malema"
    assert question["politician"] is not None
    assert "Malema" in question["politician"]["display_name"]
    assert question["archive_path"]

    detail = client.get(f"/questions/{question['id']}")
    assert detail.status_code == 200
    assert detail.json()["mentions"]

    politician_questions = client.get(f"/politicians/{question['politician']['id']}/questions")
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

    question = next(item for item in client.get("/questions?limit=500").json() if item["source_url"] == url)
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


def test_pdf_utils_archive_detection_and_mocked_extraction(monkeypatch):
    assert is_pdf_url("https://www.parliament.gov.za/storage/app/media/Docs/exe_rq_na/example.pdf")
    assert not is_pdf_url("https://www.parliament.gov.za/questions-and-replies")

    path = archive_pdf("Parliamentary Questions", "https://example.test/question/NW1.pdf", b"%PDF-1.4\n")
    assert path.endswith(".pdf")
    assert "parliament_questions" in path

    class FakePage:
        def extract_text(self):
            return "Question Number: NW1"

    class FakeReader:
        def __init__(self, file_path):
            self.pages = [FakePage()]

    monkeypatch.setattr("app.ingestion.pdf_utils.PdfReader", FakeReader)
    assert extract_pdf_text(path) == "Question Number: NW1"


def test_parliamentary_question_pdf_ingestion(monkeypatch):
    client.post("/ingest/seed")
    url = "https://www.parliament.gov.za/storage/app/media/Docs/exe_rq_na/NW42.pdf"
    text = (
        "Question Number: NW42 Asked By: Julius Malema Department: Basic Education "
        "Minister: Minister of Basic Education Question: What repairs are planned? "
        "Answer: Repairs are planned in phases."
    )
    monkeypatch.setattr("app.ingestion.parliament_questions.download_file", lambda _: b"%PDF-1.4\n")
    monkeypatch.setattr("app.ingestion.parliament_questions.extract_pdf_text", lambda _: text)

    response = client.post("/ingest/parliamentary-questions", json={"urls": [url]})
    assert response.status_code == 200
    assert response.json()["processed_count"] == 1

    question = next(item for item in client.get("/questions?limit=500").json() if item["source_url"] == url)
    assert question["source_file_type"] == "PDF"
    assert question["extracted_text_available"] is True
    assert question["parse_status"] == "PARSED"
    assert question["politician"] is not None


def test_bad_pdf_is_archived_without_crashing(monkeypatch):
    url = "https://www.parliament.gov.za/storage/app/media/Docs/exe_rq_na/bad.pdf"
    monkeypatch.setattr("app.ingestion.parliament_questions.download_file", lambda _: b"not a pdf")
    monkeypatch.setattr(
        "app.ingestion.parliament_questions.extract_pdf_text",
        lambda _: (_ for _ in ()).throw(ValueError("PDF text extraction failed: broken")),
    )

    response = client.post("/ingest/parliamentary-questions", json={"urls": [url]})
    assert response.status_code == 200
    assert response.json()["processed_count"] == 1

    question = next(item for item in client.get("/questions?limit=500").json() if item["source_url"] == url)
    assert question["source_file_type"] == "PDF"
    assert question["parse_status"] == "FAILED"
    assert question["archive_path"]


def test_parliamentary_question_discovery_extracts_pdf_links():
    html = """
    <html><body>
      <a href="/storage/app/media/Docs/exe_rq_na/RNW123-2026.pdf">Question Reply 2026</a>
      <a href="https://archive.parliament.gov.za/handle/123456789/5997">Question Paper NA 2026</a>
      <a href="/ordinary-page">Not relevant</a>
    </body></html>
    """
    urls = urls_from_listing("https://www.parliament.gov.za/questions-and-replies", html, year=2026)
    assert "https://www.parliament.gov.za/storage/app/media/Docs/exe_rq_na/RNW123-2026.pdf" in urls
    assert "https://archive.parliament.gov.za/handle/123456789/5997" in urls
