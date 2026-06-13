"""Tests for the report-only entity-resolution candidate suggestions."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from report_entity_resolution_candidates import (
    assess,
    build_report,
    confidence_bucket,
    redact,
    render_markdown,
    write_report,
)


def _unresolved(raw="Malema", **kw):
    base = {"id": "u1", "raw_value": raw, "entity_type": "politician",
            "source_name": "PMG", "source_url": "https://pmg.org.za/x"}
    base.update(kw)
    return base


def test_confidence_bucket_thresholds():
    assert confidence_bucket(0.99, ambiguous=False) == "high"
    assert confidence_bucket(0.80, ambiguous=False) == "medium"
    assert confidence_bucket(0.50, ambiguous=False) == "low"
    assert confidence_bucket(0.99, ambiguous=True) == "low"  # ambiguity always low


def test_exact_alias_gives_high_confidence():
    candidates = [{"politician_id": "p1", "politician_name": "Julius Malema", "party": "EFF",
                   "score": 0.99, "signals": "exact_full_name", "reason": "exact_full_name"}]
    result = assess(_unresolved("Julius Malema"), candidates)
    assert result["confidence_bucket"] == "high"
    assert result["recommended_for_review"] is True
    assert result["candidates"][0]["politician_name"] == "Julius Malema"


def test_weak_name_only_match_is_not_high():
    candidates = [{"politician_id": "p1", "politician_name": "A B", "party": None,
                   "score": 0.72, "signals": "unique_surname", "reason": "unique_surname"}]
    result = assess(_unresolved("Surname"), candidates)
    assert result["confidence_bucket"] == "medium"
    assert result["recommended_for_review"] is False


def test_ambiguous_multiple_candidates_remain_unresolved():
    candidates = [
        {"politician_id": "p1", "politician_name": "A Mokoena", "party": "ANC", "score": 0.72, "signals": "surname_ambiguous", "reason": "x"},
        {"politician_id": "p2", "politician_name": "B Mokoena", "party": "DA", "score": 0.72, "signals": "surname_ambiguous", "reason": "x"},
    ]
    result = assess(_unresolved("Mokoena"), candidates)
    assert result["ambiguous"] is True
    assert result["confidence_bucket"] == "low"
    assert result["recommended_for_review"] is False
    assert "ambiguous" in result["reason"].lower()


def test_no_candidate_is_unresolved_low():
    result = assess(_unresolved("Nobody"), [])
    assert result["confidence_bucket"] == "low"
    assert result["recommended_for_review"] is False
    assert result["candidates"] == []


def test_build_report_counts_and_min_score():
    records = [_unresolved("Julius Malema", id="u1"), _unresolved("Ghost", id="u2")]

    def finder(raw):
        if raw == "Julius Malema":
            return [{"politician_id": "p1", "politician_name": "Julius Malema", "party": "EFF",
                     "score": 0.99, "signals": "exact_full_name", "reason": "exact_full_name"}]
        return []

    report = build_report(records, finder, min_score=0.0)
    assert report["total_assessed"] == 2
    assert report["bucket_counts"]["high"] == 1
    assert report["recommended_for_review_count"] == 1


def test_min_score_filters_weak_candidates():
    records = [_unresolved("Weak", id="u1")]

    def finder(raw):
        return [{"politician_id": "p1", "politician_name": "X", "party": None,
                 "score": 0.5, "signals": "weak", "reason": "weak"}]

    report = build_report(records, finder, min_score=0.7)
    assert report["assessments"][0]["candidates"] == []  # filtered out


def test_output_json_valid_and_files_written(tmp_path):
    report = build_report([_unresolved()], lambda r: [], min_score=0.0)
    json_path, md_path = write_report(report, tmp_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["total_assessed"] == 1
    assert md_path.read_text(encoding="utf-8").startswith("# Entity Resolution Candidate Review")


def test_markdown_includes_review_instructions_and_policy():
    md = render_markdown(build_report([_unresolved()], lambda r: [], min_score=0.0))
    assert "How to review" in md
    assert "suggestions only" in md
    assert "no matches are applied" in md.lower() or "nothing has been applied" in md.lower()
    assert "## Policy" in md


def test_no_secrets_in_source_url():
    rec = _unresolved(source_url="postgresql://user:hunter2@host/db")
    result = assess(rec, [])
    assert "hunter2" not in json.dumps(result)
    assert "[REDACTED]@" in result["source_url"]


def test_redact_handles_none():
    assert redact(None) is None
    assert redact("https://pmg.org.za/x") == "https://pmg.org.za/x"
