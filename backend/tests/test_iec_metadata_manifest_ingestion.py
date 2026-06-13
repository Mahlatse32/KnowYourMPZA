"""Tests for IEC metadata + source manifest ingestion (#24). No live network."""
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from app.db import Base
from app.models.iec_election import IECElection
from app.models.iec_source_manifest import IECSourceManifest

from ingest_iec_metadata_manifest import (
    build_report,
    build_rows,
    election_key_for,
    manifest_key_for,
    normalize_url,
    parser_readiness,
    redact,
    render_markdown,
    run_ingest,
    write_report,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


# Curated-style fixture sources mirroring KNOWN_IEC_SOURCES shape.
SOURCES = [
    {"url": "https://results.elections.org.za/home/", "election_type": "all", "year": None,
     "geography_level": "national/provincial/municipal", "notes": "portal"},
    {"url": "https://results.elections.org.za/dashboards/npe/", "election_type": "national", "year": None,
     "geography_level": "national", "notes": "npe"},
    {"url": "https://results.elections.org.za/dashboards/lge/", "election_type": "municipal", "year": None,
     "geography_level": "municipal/ward", "notes": "lge"},
]


def _fetcher(ok=True, status=200, content_type="text/html", body=None):
    def fetch(url):
        return {"status": status, "content_type": content_type, "ok": ok, "body": body}

    return fetch


# ---------------------------------------------------------------------------
# 1. Migration/model creates the tables
# ---------------------------------------------------------------------------

def test_tables_created(db):
    names = set(inspect(db.get_bind()).get_table_names())
    assert "iec_elections" in names
    assert "iec_source_manifests" in names


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------

def test_normalize_url_strips_trailing_slash_and_fragment():
    assert normalize_url("https://X.org/Home/#frag") == "https://x.org/Home"
    assert normalize_url("https://x.org/a/?q=1") == "https://x.org/a?q=1"


def test_election_key_only_for_concrete_types():
    assert election_key_for("national", None) == "national"
    assert election_key_for("municipal", 2021) == "municipal-2021"
    assert election_key_for("all", None) is None       # portal/landing → no election
    assert election_key_for("unknown", None) is None


def test_manifest_key_stable_and_deterministic():
    k1 = manifest_key_for("https://results.elections.org.za/dashboards/npe/", "national")
    k2 = manifest_key_for("https://results.elections.org.za/dashboards/npe/", "national")
    assert k1 == k2
    assert k1.endswith("#national")


def test_parser_readiness_mapping():
    assert parser_readiness("csv", True) == "structured-candidate"
    assert parser_readiness("html", True) == "needs-parser-design"
    assert parser_readiness("csv", False) == "unreachable"


# ---------------------------------------------------------------------------
# build_rows: elections only for concrete types; no fabrication
# ---------------------------------------------------------------------------

def test_build_rows_elections_and_manifests():
    built = build_rows(SOURCES, _fetcher())
    assert built["attempted"] == 3
    assert len(built["manifests"]) == 3
    # "all" portal makes no election; national + municipal do
    ekeys = {e["election_key"] for e in built["elections"]}
    assert ekeys == {"national", "municipal"}
    for e in built["elections"]:
        assert e["source_date"] is None           # dates never invented
        assert e["name"] is None                   # names never invented
        assert e["raw_metadata_json"]["vote_totals_ingested"] is False


def test_build_rows_preserves_source_url_exactly():
    built = build_rows(SOURCES, _fetcher())
    urls = {m["source_url"] for m in built["manifests"]}
    assert "https://results.elections.org.za/home/" in urls  # exact, trailing slash kept


def test_checksum_computed_only_when_body_present():
    no_body = build_rows(SOURCES, _fetcher(body=None))
    assert all(m["checksum_sha256"] is None for m in no_body["manifests"])
    with_body = build_rows(SOURCES, _fetcher(body="col1,col2\n1,2\n", content_type="text/csv"))
    m = with_body["manifests"][0]
    assert m["checksum_sha256"] is not None and len(m["checksum_sha256"]) == 64
    assert m["byte_size"] == len("col1,col2\n1,2\n")


# ---------------------------------------------------------------------------
# Real-mode upsert + idempotency
# ---------------------------------------------------------------------------

def test_real_run_upserts_rows(db):
    summary = run_ingest(db, SOURCES, _fetcher(), dry_run=False)
    assert summary["created_manifests"] == 3
    assert summary["created_elections"] == 2
    assert db.scalar(select(IECSourceManifest).where(IECSourceManifest.source_url == SOURCES[0]["url"])) is not None
    manifests = list(db.scalars(select(IECSourceManifest)))
    assert all(m.source_url for m in manifests)  # source URL retained


def test_rerun_is_idempotent(db):
    run_ingest(db, SOURCES, _fetcher(), dry_run=False)
    second = run_ingest(db, SOURCES, _fetcher(), dry_run=False)
    assert second["created_manifests"] == 0
    assert second["updated_manifests"] == 3
    assert second["created_elections"] == 0
    assert second["updated_elections"] == 2
    assert len(list(db.scalars(select(IECSourceManifest)))) == 3
    assert len(list(db.scalars(select(IECElection)))) == 2


def test_dry_run_writes_nothing(db):
    summary = run_ingest(db, SOURCES, _fetcher(), dry_run=True)
    assert summary["mode"] == "dry-run"
    assert db.scalar(select(IECSourceManifest).limit(1)) is None
    assert db.scalar(select(IECElection).limit(1)) is None


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------

def test_one_source_failure_does_not_abort(db):
    def flaky(url):
        if "npe" in url:
            raise ConnectionError("boom")
        return {"status": 200, "content_type": "text/html", "ok": True}

    summary = run_ingest(db, SOURCES, flaky, dry_run=False)
    assert summary["failed_sources"] == 1
    assert summary["created_manifests"] == 2  # other two still ingested


def test_all_sources_fail_reported(db):
    def broken(url):
        raise ConnectionError("down")

    summary = run_ingest(db, SOURCES, broken, dry_run=False)
    report = build_report(summary)
    assert report["failed_sources"] == report["attempted_sources"] == 3
    assert report["manifests_built"] == 0


# ---------------------------------------------------------------------------
# No vote totals / winners / office-bearers
# ---------------------------------------------------------------------------

def test_no_vote_totals_or_winners(db):
    run_ingest(db, SOURCES, _fetcher(), dry_run=False)
    report = build_report(run_ingest(db, SOURCES, _fetcher(), dry_run=True))
    assert report["vote_totals_ingested"] is False
    # No result/vote/winner/office-bearer columns exist on either model.
    for model in (IECSourceManifest, IECElection):
        cols = {c.name for c in model.__table__.columns}
        assert not any(
            tok in c
            for c in cols
            for tok in ("vote", "winner", "result", "councillor", "office_bearer", "candidate")
        )
    # No such rows exist either (tables for them were never created).
    names = set(inspect(db.get_bind()).get_table_names())
    assert "iec_vote_totals" not in names and "iec_results" not in names


# ---------------------------------------------------------------------------
# Reports: JSON/MD valid, parser readiness counts, secret redaction
# ---------------------------------------------------------------------------

def test_report_files_written_and_valid(tmp_path):
    summary = run_ingest(None, SOURCES, _fetcher(), dry_run=True)
    report = build_report(summary)
    json_path, md_path = write_report(report, tmp_path)
    parsed = json.loads(json_path.read_text(encoding="utf-8"))
    assert parsed["mode"] == "dry-run"
    md = md_path.read_text(encoding="utf-8")
    assert "IEC Metadata & Source Manifest Ingestion" in md
    assert "**Vote totals ingested:** False" in md


def test_parser_readiness_counts(tmp_path):
    # one csv (structured), two html (needs-parser-design)
    def fetch(url):
        ct = "text/csv" if "home" in url else "text/html"
        return {"status": 200, "content_type": ct, "ok": True}

    report = build_report(run_ingest(None, SOURCES, fetch, dry_run=True))
    counts = report["parser_readiness_counts"]
    assert counts.get("structured-candidate") == 1
    assert counts.get("needs-parser-design") == 2


def test_secret_redaction_in_failures():
    def leaky(url):
        raise ConnectionError("connect postgresql://user:hunter2@host/db failed")

    report = build_report(run_ingest(None, SOURCES, leaky, dry_run=True))
    blob = json.dumps(report)
    # error messages are truncated/stored; ensure no embedded URL credentials survive in source_url
    for f in report["failures"]:
        assert "hunter2" not in (f.get("source_url") or "")
    assert redact("https://u:hunter2@h/x").count("[REDACTED]@") == 1


def test_coverage_counts_by_type(tmp_path):
    report = build_report(run_ingest(None, SOURCES, _fetcher(), dry_run=True))
    by_type = report["coverage_by_election_type"]
    assert by_type.get("all") == 1
    assert by_type.get("national") == 1
    assert by_type.get("municipal") == 1
