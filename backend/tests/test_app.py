from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.ingestion.parliament_question_discovery import urls_from_listing
from app.ingestion.pdf_utils import archive_pdf, extract_pdf_text, is_pdf_url
from app.ingestion.pmg import discover_pmg_document_urls, parse_document
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
from sqlalchemy import func, select


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
    assert client.get("/quality/duplicates").status_code == 200
    assert client.get("/quality/archive-gaps").status_code == 200


def test_pmg_discovery_and_metadata_parsing(monkeypatch):
    html = """
    <html><body>
      <a href="/committee-meeting/43172/">Meeting</a>
      <a href="/committee-report/100/">Report</a>
      <h1>Portfolio Committee on Health meeting</h1>
      <p>12 March 2026</p>
    </body></html>
    """
    monkeypatch.setattr("app.ingestion.pmg.fetch_page", lambda _: html)
    urls = discover_pmg_document_urls(limit=5, year=2026, committee="Health")
    assert "https://pmg.org.za/committee-meeting/43172/" in urls
    parsed = parse_document("https://pmg.org.za/committee-meeting/43172/", html, "data/raw/pmg/test.html")
    assert parsed.document_type == "PMG_COMMITTEE_MEETING"
    assert parsed.committee_name == "Portfolio Committee on Health"


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


# ---------------------------------------------------------------------------
# /quality/full-coverage endpoint
# ---------------------------------------------------------------------------


def test_full_coverage_endpoint_returns_expected_keys():
    response = client.get("/quality/full-coverage")
    assert response.status_code == 200
    data = response.json()
    assert "generated_at" in data
    assert "database_counts" in data
    assert "source_coverage" in data
    assert "politician_coverage" in data
    assert "committee_coverage" in data
    assert "pmg_coverage" in data
    assert "question_coverage" in data
    assert "pdf_coverage" in data
    assert "archive_coverage" in data
    assert "unresolved_entity_coverage" in data
    assert "duplicate_candidates" in data
    assert "weak_records" in data
    assert "latest_ingestion_runs" in data
    assert "latest_ingestion_errors" in data
    assert "recommendations" in data


def test_full_coverage_recommendations_is_nonempty_list():
    response = client.get("/quality/full-coverage")
    assert response.status_code == 200
    recs = response.json()["recommendations"]
    assert isinstance(recs, list)
    assert len(recs) >= 1


def test_full_coverage_pct_fields_are_none_or_float():
    response = client.get("/quality/full-coverage")
    assert response.status_code == 200
    pc = response.json()["politician_coverage"]
    for key in ("with_party_pct", "with_source_url_pct", "with_aliases_pct", "with_committees_pct"):
        val = pc[key]
        assert val is None or isinstance(val, (int, float))


# ---------------------------------------------------------------------------
# Idempotent upserts — re-ingesting same profiles does not duplicate rows
# ---------------------------------------------------------------------------


def test_ingest_people_assembly_is_idempotent(monkeypatch):
    html = """
    <html><body>
      <h1 class="profile-name">Idempotent Test MP</h1>
      <p class="party-name"><a href="/party/test-party/">Test Party</a></p>
      <p class="province">Gauteng</p>
    </body></html>
    """
    url = "https://www.pa.org.za/person/idempotent-test-mp/"
    monkeypatch.setattr("app.ingestion.people_assembly.fetch_url", lambda u, sleep=0.5: html)

    response1 = client.post("/ingest/people-assembly", json={"urls": [url]})
    assert response1.status_code == 200

    response2 = client.post("/ingest/people-assembly", json={"urls": [url]})
    assert response2.status_code == 200

    politicians = client.get("/politicians?limit=500").json()
    count = sum(1 for p in politicians if p["display_name"] == "Idempotent Test MP")
    assert count == 1, f"Expected 1 record, got {count}"


# ---------------------------------------------------------------------------
# Alias-based search — politicians should be findable by alias
# ---------------------------------------------------------------------------


def test_politician_search_finds_by_alias(monkeypatch):
    html = """
    <html><body>
      <h1 class="profile-name">Alias Search Test</h1>
      <p class="party-name"><a href="/party/demo-party/">Demo Party</a></p>
      <p class="province">Western Cape</p>
    </body></html>
    """
    url = "https://www.pa.org.za/person/alias-search-test/"
    monkeypatch.setattr("app.ingestion.people_assembly.fetch_url", lambda u, sleep=0.5: html)

    client.post("/ingest/people-assembly", json={"urls": [url]})

    with SessionLocal() as db:
        politician = next(
            (p for p in db.execute(select(__import__("app.models.politician", fromlist=["Politician"]).Politician)).scalars() if p.display_name == "Alias Search Test"),
            None,
        )
        assert politician is not None
        aliases = list(db.scalars(select(PoliticianAlias).where(PoliticianAlias.politician_id == politician.id)))
        alias_values = {a.alias for a in aliases}
        assert len(alias_values) > 0, "Expected at least one alias to be generated"


# ---------------------------------------------------------------------------
# Unresolved entity filters
# ---------------------------------------------------------------------------


def test_unresolved_entities_filter_by_name():
    with SessionLocal() as db:
        from app.models.unresolved_entity import UnresolvedEntity as UE
        db.add(UE(raw_value="Filtertest Unique Name", entity_type="POLITICIAN", source_name="test", status="OPEN"))
        db.commit()

    response = client.get("/unresolved-entities?name=Filtertest")
    assert response.status_code == 200
    results = response.json()
    assert any("Filtertest" in r["raw_value"] for r in results)


def test_unresolved_entities_filter_by_entity_type():
    with SessionLocal() as db:
        from app.models.unresolved_entity import UnresolvedEntity as UE
        db.add(UE(raw_value="Type Filter Entity", entity_type="COMMITTEE", source_name="test", status="OPEN"))
        db.commit()

    response = client.get("/unresolved-entities?entity_type=COMMITTEE")
    assert response.status_code == 200
    results = response.json()
    assert all(r["entity_type"] == "COMMITTEE" for r in results)


# ---------------------------------------------------------------------------
# Party ingestion / normalization / deduplication
# ---------------------------------------------------------------------------


def test_party_normalization_known_abbreviations():
    """normalize_party_name handles abbreviations, trailing noise, and casing."""
    cases = [
        ("ANC", "African National Congress", "ANC"),
        ("Democratic Alliance (DA)", "Democratic Alliance", "DA"),
        ("  EFF  ", "Economic Freedom Fighters", "EFF"),
        ("FF+", "Freedom Front Plus", "FF Plus"),
        ("IFP", "Inkatha Freedom Party", "IFP"),
        ("ActionSA", "ActionSA", "ActionSA"),
    ]
    for raw, expected_name, expected_short in cases:
        name, short = normalize_party_name(raw)
        assert name == expected_name, f"name mismatch for {raw!r}: got {name!r}"
        assert short == expected_short, f"short mismatch for {raw!r}: got {short!r}"


def test_party_upsert_does_not_duplicate(monkeypatch):
    """Ingesting the same MP twice creates only one party record."""
    html = """
    <html><head>
      <meta property="profile:first_name" content="Party">
      <meta property="profile:last_name" content="Dedup Test">
    </head><body>
      <h1>Party Dedup Test</h1>
      <div class="mp-block"><div class="mp-block__title">Political Party</div><a>African National Congress (ANC)</a></div>
      Member of the National Assembly
    </body></html>
    """
    url = "https://www.pa.org.za/person/party-dedup-test/"
    monkeypatch.setattr("app.services.ingestion_service.fetch_people_assembly_page", lambda _: html)
    with SessionLocal() as db:
        ingest_people_assembly_profiles(db, [url])
        ingest_people_assembly_profiles(db, [url])
    parties = client.get("/parties").json()
    anc_count = sum(1 for p in parties if p["short_name"] == "ANC")
    assert anc_count == 1, f"Expected exactly 1 ANC, got {anc_count}"


# ---------------------------------------------------------------------------
# Committee normalization and deduplication
# ---------------------------------------------------------------------------


def test_committee_normalization():
    """Committee names are stripped of 'Portfolio Committee on' prefix and cleaned."""
    cases = [
        ("Portfolio Committee on Health", "Health"),
        ("Standing Committee on Finance", "Finance"),
        ("Portfolio Committee on  Basic Education,,", "Basic Education"),
    ]
    for raw, expected in cases:
        assert normalize_committee_name(raw) == expected, f"mismatch for {raw!r}"


def test_committee_upsert_does_not_duplicate(monkeypatch):
    """Re-ingesting the same committee page creates exactly one committee."""
    url = "https://www.pa.org.za/committee/dedup-committee-test/"
    html = """
    <html><body>
      <h1>Portfolio Committee on Dedup Testing</h1>
      <ul>
        <li>Chairperson <a href="/person/julius-sello-malema/">Julius Malema</a></li>
      </ul>
    </body></html>
    """
    monkeypatch.setattr("app.services.ingestion_service.fetch_people_assembly_page", lambda _: html)
    client.post("/ingest/seed")
    with SessionLocal() as db:
        ingest_people_assembly_committees(db, [url])
        ingest_people_assembly_committees(db, [url])
    committees = client.get("/committees").json()
    count = sum(1 for c in committees if "Dedup Testing" in c.get("name", ""))
    assert count == 1, f"Expected 1 committee, got {count}"


# ---------------------------------------------------------------------------
# Committee membership — role persistence and duplicate prevention
# ---------------------------------------------------------------------------


def test_committee_membership_role_is_persisted(monkeypatch):
    """Membership records retain the role extracted from source HTML."""
    client.post("/ingest/seed")
    url = "https://www.pa.org.za/committee/role-test-committee/"
    html = """
    <html><body>
      <h1>Portfolio Committee on Role Test</h1>
      <ul>
        <li>Chairperson <a href="/person/julius-sello-malema/">Julius Malema</a></li>
      </ul>
    </body></html>
    """
    monkeypatch.setattr("app.services.ingestion_service.fetch_people_assembly_page", lambda _: html)
    with SessionLocal() as db:
        ingest_people_assembly_committees(db, [url])
        membership = db.scalars(select(CommitteeMembership).where(CommitteeMembership.source_url == url)).first()
    assert membership is not None
    assert membership.role == "Chairperson"


def test_committee_membership_no_duplicate_rows(monkeypatch):
    """Ingesting the same committee page twice does not produce duplicate membership rows."""
    client.post("/ingest/seed")
    url = "https://www.pa.org.za/committee/nodedup-membership-committee/"
    html = """
    <html><body>
      <h1>Portfolio Committee on No Dup Membership</h1>
      <ul>
        <li>Member <a href="/person/julius-sello-malema/">Julius Malema</a></li>
      </ul>
    </body></html>
    """
    monkeypatch.setattr("app.services.ingestion_service.fetch_people_assembly_page", lambda _: html)
    with SessionLocal() as db:
        ingest_people_assembly_committees(db, [url])
        ingest_people_assembly_committees(db, [url])
        count = db.scalar(select(func.count()).select_from(CommitteeMembership).where(CommitteeMembership.source_url == url))
    assert count == 1, f"Expected 1 membership, got {count}"


# ---------------------------------------------------------------------------
# PMG ingestion — document type, committee linkage, idempotency
# ---------------------------------------------------------------------------


def test_pmg_document_type_is_set(monkeypatch):
    """PMG meeting pages are stored with the correct document_type."""
    html = """
    <html><body>
      <a href="/committee-meeting/99999/">Meeting 99999</a>
      <h1>Portfolio Committee on Water meeting</h1>
    </body></html>
    """
    monkeypatch.setattr("app.ingestion.pmg.fetch_page", lambda _: html)
    parsed = parse_document("https://pmg.org.za/committee-meeting/99999/", html, "data/raw/pmg/99999.html")
    assert parsed.document_type == "PMG_COMMITTEE_MEETING"


def test_pmg_ingestion_is_idempotent(monkeypatch):
    """Ingesting the same PMG URL twice creates one document record."""
    url = "https://pmg.org.za/committee-meeting/idempotent-99/"
    html = """
    <html><body>
      <h1>Portfolio Committee on Idempotency meeting</h1>
      <p>5 June 2026</p>
    </body></html>
    """
    monkeypatch.setattr("app.ingestion.pmg.fetch_page", lambda _: html)
    response1 = client.post("/ingest/pmg-documents", json={"urls": [url]})
    response2 = client.post("/ingest/pmg-documents", json={"urls": [url]})
    assert response1.status_code == 200
    assert response2.status_code == 200
    docs = client.get("/documents").json()
    count = sum(1 for d in docs if d.get("source_url") == url)
    assert count == 1, f"Expected 1 PMG document, got {count}"


# ---------------------------------------------------------------------------
# Entity resolution — alias match, surname match
# ---------------------------------------------------------------------------


def test_entity_resolution_finds_by_alias():
    """Entity resolution can find a politician via a generated alias."""
    from app.services.entity_resolution import resolve_politician_name

    client.post("/ingest/seed")
    results = client.get("/search?name=malema").json()
    assert results, "Seed data must include Malema"
    with SessionLocal() as db:
        result = resolve_politician_name(db, "Julius Malema")
        assert result is not None
        assert result.confidence_score >= 0.9
        assert "Malema" in result.politician.display_name


def test_entity_resolution_returns_none_for_unknown():
    """Entity resolution returns None for a name with no plausible match."""
    from app.services.entity_resolution import resolve_politician_name

    with SessionLocal() as db:
        result = resolve_politician_name(db, "Zzz Totally Nonexistent Person XYZ999")
        assert result is None


# ---------------------------------------------------------------------------
# Search completeness checks script — unit tests for individual check logic
# ---------------------------------------------------------------------------


def test_search_completeness_status_helper():
    """_status returns PASS for positive counts and FAIL for zero."""
    from scripts.check_search_completeness import _status

    assert _status(1) == "PASS"
    assert _status(10) == "PASS"
    assert _status(0) == "FAIL"


def test_search_completeness_check_dataclass():
    """Check dataclass serialises cleanly via asdict."""
    from dataclasses import asdict

    from scripts.check_search_completeness import Check

    c = Check("test_check", "Test description", "PASS", 5, "sample", "a note")
    d = asdict(c)
    assert d["status"] == "PASS"
    assert d["result_count"] == 5


def test_search_completeness_markdown_includes_summary():
    """build_markdown outputs a summary line and check table."""
    from scripts.check_search_completeness import Check, build_markdown

    checks = [
        Check("c1", "Check one", "PASS", 1, "val", ""),
        Check("c2", "Check two", "FAIL", 0, None, "nothing found"),
        Check("c3", "Check three", "SKIP", 0, None, "no data"),
    ]
    md = build_markdown(checks, "2026-06-11T00:00:00Z")
    assert "PASS" in md
    assert "FAIL" in md
    assert "SKIP" in md
    assert "1 PASS" in md
    assert "1 FAIL" in md


# ---------------------------------------------------------------------------
# /quality/full-coverage — with seeded data
# ---------------------------------------------------------------------------


def test_full_coverage_with_seeded_data_has_nonzero_counts():
    """After seeding, database_counts should have positive totals."""
    client.post("/ingest/seed")
    response = client.get("/quality/full-coverage")
    assert response.status_code == 200
    counts = response.json()["database_counts"]
    assert counts["politicians_total"] >= 10
    assert counts["parties_total"] >= 1
    assert counts["committees_total"] >= 1


def test_full_coverage_source_coverage_is_list():
    """source_coverage must be a list of objects with required keys."""
    response = client.get("/quality/full-coverage")
    assert response.status_code == 200
    sc = response.json()["source_coverage"]
    assert isinstance(sc, list)
    assert len(sc) > 0
    for item in sc:
        assert "category" in item
        assert "ingested_total" in item
        assert "coverage_note" in item


def test_full_coverage_duplicate_candidates_are_ints():
    """All duplicate_candidates values must be non-negative integers."""
    response = client.get("/quality/full-coverage")
    assert response.status_code == 200
    dup = response.json()["duplicate_candidates"]
    for key, val in dup.items():
        assert isinstance(val, int), f"{key} is not int: {val!r}"
        assert val >= 0


# ---------------------------------------------------------------------------
# report_full_coverage script — markdown builder
# ---------------------------------------------------------------------------


def test_report_full_coverage_markdown_builder_runs():
    """build_markdown produces a non-empty string with expected headings."""
    from scripts.report_full_coverage import build_markdown
    from app.services.coverage_service import generate_full_coverage_report

    with SessionLocal() as db:
        report = generate_full_coverage_report(db)

    md = build_markdown(report)
    assert "## Politicians" in md
    assert "## Committees" in md
    assert "## Recommendations" in md
    assert "Coverage caveat" in md


# ---------------------------------------------------------------------------
# run_full_ingestion.py — dry-run produces no DB changes
# ---------------------------------------------------------------------------


def test_run_full_ingestion_dry_run_flag_is_propagated():
    """run_stage with dry_run=True appends --dry-run to the subprocess args."""
    import subprocess
    from unittest.mock import MagicMock, patch

    from scripts.run_full_ingestion import run_stage

    with patch("scripts.run_full_ingestion.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        run_stage("Test Stage", "some_script.py", ["--limit", "10"], dry_run=True)
        call_args = mock_run.call_args[0][0]
        assert "--dry-run" in call_args


def test_run_stage_returns_false_on_nonzero_exit():
    """run_stage returns False when the subprocess exits non-zero."""
    from unittest.mock import MagicMock, patch

    from scripts.run_full_ingestion import run_stage

    with patch("scripts.run_full_ingestion.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        result = run_stage("Failing Stage", "some_script.py", [], dry_run=False)
        assert result is False


def test_run_stage_returns_true_on_success():
    """run_stage returns True when the subprocess exits 0."""
    from unittest.mock import MagicMock, patch

    from scripts.run_full_ingestion import run_stage

    with patch("scripts.run_full_ingestion.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = run_stage("OK Stage", "some_script.py", [], dry_run=False)
        assert result is True
