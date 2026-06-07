from fastapi.testclient import TestClient

from app.ingestion.people_assembly import create_slug
from app.main import app


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
