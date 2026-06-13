"""Tests for the bounded IEC live download audit (#24). Offline only — no network, no DB."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from audit_iec_live_downloads import (
    EXPECTED_CSV_COLUMNS,
    audit_one,
    build_audit,
    detect_csv_columns,
    is_official_iec,
    redact,
    render_markdown,
    write_report,
)

OFFICIAL = "https://results.elections.org.za/dashboards/npe/data.csv"
NON_OFFICIAL = "https://example.com/results.csv"
CSV_GOOD = "Contest_ID,Contest_Name,Party_ID,Party_Name,Votes\n1,Ward 1,DA,DA,123\n"
CSV_BAD = "Foo,Bar\n1,2\n"


def _resp(**kw):
    base = {"status": 200, "content_type": "text/csv", "content_length": len(CSV_GOOD),
            "body": CSV_GOOD, "final_url": None}
    base.update(kw)
    return base


def _fetcher(mapping):
    def fetch(url):
        if url not in mapping:
            raise ConnectionError(f"no response for {url}")
        return mapping[url]
    return fetch


# ---------------------------------------------------------------------------
# Domain + helpers
# ---------------------------------------------------------------------------

def test_official_iec_accepted():
    assert is_official_iec(OFFICIAL)
    assert is_official_iec("https://www.elections.org.za/pw/Downloads")


def test_non_iec_url_rejected():
    assert not is_official_iec(NON_OFFICIAL)
    assert not is_official_iec("https://elections.org.za.evil.com/x")  # suffix-spoof not official


def test_csv_header_detected():
    cols = detect_csv_columns(CSV_GOOD)
    assert "contest_id" in cols and "party_id" in cols and "votes" in cols
    assert EXPECTED_CSV_COLUMNS.issubset(set(cols))


# ---------------------------------------------------------------------------
# audit_one
# ---------------------------------------------------------------------------

def test_audit_good_csv_is_structured_candidate():
    rec = audit_one(OFFICIAL, _resp(), max_bytes=1_000_000)
    assert rec["reachable"] is True
    assert rec["source_format"] == "csv"
    assert rec["has_expected_csv_columns"] is True
    assert rec["likely_parser_profile"] == "structured-candidate"
    assert rec["risk_flags"] == []
    assert rec["checksum_sha256"] is not None and len(rec["checksum_sha256"]) == 64
    assert rec["rows_written_to_db"] is False


def test_csv_missing_columns_flagged():
    rec = audit_one(OFFICIAL, _resp(body=CSV_BAD, content_length=len(CSV_BAD)), max_bytes=1_000_000)
    assert "csv_header_missing_expected_columns" in rec["risk_flags"]
    assert rec["has_expected_csv_columns"] is False


def test_oversize_response_marked_unsafe():
    rec = audit_one(OFFICIAL, _resp(content_length=5_000_000), max_bytes=1_000_000)
    assert "oversize" in rec["risk_flags"]


def test_body_sampled_when_cap_hit():
    big = "x" * 50
    rec = audit_one(OFFICIAL, _resp(body=big, content_length=len(big)), max_bytes=10)
    assert rec["body_sampled"] is True
    assert "body_sampled_not_full" in rec["risk_flags"]


def test_redirect_off_domain_rejected():
    rec = audit_one(OFFICIAL, _resp(final_url="https://example.com/elsewhere.csv"), max_bytes=1_000_000)
    assert "redirect_off_official_domain" in rec["risk_flags"]
    assert rec["reachable"] is False


def test_checksum_computed_for_bounded_body():
    import hashlib
    rec = audit_one(OFFICIAL, _resp(), max_bytes=1_000_000)
    assert rec["checksum_sha256"] == hashlib.sha256(CSV_GOOD.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# build_audit
# ---------------------------------------------------------------------------

def test_non_official_url_rejected_in_build():
    report = build_audit([NON_OFFICIAL], _fetcher({}), max_bytes=1_000_000)
    assert report["audited_count"] == 0
    assert report["failed_count"] == 1
    assert report["rejected_non_official"] == [NON_OFFICIAL]


def test_per_url_failure_isolation():
    mapping = {OFFICIAL: _resp()}
    other = "https://results.elections.org.za/missing.csv"
    report = build_audit([OFFICIAL, other], _fetcher(mapping), max_bytes=1_000_000)
    assert report["audited_count"] == 1
    assert report["failed_count"] == 1


def test_all_fail_reported():
    report = build_audit([NON_OFFICIAL, "https://other.com/x"], _fetcher({}), max_bytes=1_000_000)
    assert report["attempted_urls"] == 2
    assert report["failed_count"] == 2
    assert report["audited_count"] == 0


def test_no_db_writes_flag_everywhere():
    report = build_audit([OFFICIAL], _fetcher({OFFICIAL: _resp()}), max_bytes=1_000_000)
    assert all(a["rows_written_to_db"] is False for a in report["audited"])


def test_reports_written_and_valid(tmp_path):
    report = build_audit([OFFICIAL], _fetcher({OFFICIAL: _resp()}), max_bytes=1_000_000)
    json_path, md_path = write_report(report, tmp_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["audited_count"] == 1
    md = md_path.read_text(encoding="utf-8")
    assert "IEC Controlled Live Download Audit" in md
    assert "Integrity rules" in md


def test_secret_redaction():
    leaky = "https://u:hunter2@results.elections.org.za/x.csv"
    # is_official_iec sees the host; build rejects nothing here but failures redact
    out = redact(leaky)
    assert "hunter2" not in out and "[REDACTED]@" in out


def test_no_winner_or_mapping_fields():
    # Scope to the data records (not the integrity-rule prose, which names what
    # is deliberately NOT produced).
    report = build_audit([OFFICIAL], _fetcher({OFFICIAL: _resp()}), max_bytes=1_000_000)
    data_blob = json.dumps({"audited": report["audited"], "failures": report["failures"]}).lower()
    for forbidden in ("winner", "office_bearer", "councillor", "internal_party", "party_mapping"):
        assert forbidden not in data_blob
    # And no audit record carries any such key.
    for a in report["audited"]:
        assert not any("winner" in k or "mapping" in k for k in a)


def test_offline_fixture_roundtrip(tmp_path):
    from audit_iec_live_downloads import _fixture_fetcher
    fixture = {
        "urls": [OFFICIAL],
        "responses": [{"url": OFFICIAL, "status": 200, "content_type": "text/csv",
                       "content_length": len(CSV_GOOD), "body": CSV_GOOD}],
    }
    fpath = tmp_path / "f.json"
    fpath.write_text(json.dumps(fixture), encoding="utf-8")
    urls, fetcher = _fixture_fetcher(fpath)
    report = build_audit(urls, fetcher, max_bytes=1_000_000)
    assert report["audited_count"] == 1
    assert report["audited"][0]["likely_parser_profile"] == "structured-candidate"
