"""Parse the explicitly audited IEC party vote-total CSV profile."""
import csv
import hashlib
import json
from pathlib import Path


REQUIRED_COLUMNS = {"Contest_ID", "Party_ID", "Votes"}
KNOWN_COLUMNS = (
    "Contest_ID",
    "Contest_Name",
    "Province_ID",
    "Province_Name",
    "Party_ID",
    "Party_Name",
    "Candidate_ID",
    "Candidate_Name",
    "Votes",
)


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _checksum(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def result_key_for(manifest_key: str, row: dict) -> str:
    identity = {
        "manifest_key": manifest_key,
        "contest_id": row["source_contest_id"],
        "geography_id": row["source_geography_id"],
        "party_id": row["source_party_id"],
        "candidate_id": row["source_candidate_id"],
    }
    return f"iec-vote:{_checksum(identity)}"


def parse_vote_totals_csv(path: str | Path, manifest) -> dict:
    """Return valid row dictionaries and isolated row/header failures."""
    source_path = Path(path)
    rows: list[dict] = []
    failures: list[dict] = []

    with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_COLUMNS - fieldnames)
        if missing:
            return {
                "rows": [],
                "failures": [{"row_number": 1, "error_type": "MissingColumns", "error": ", ".join(missing)}],
                "input_rows": 0,
            }

        input_rows = 0
        for row_number, raw in enumerate(reader, start=2):
            input_rows += 1
            preserved = {key: raw.get(key) for key in reader.fieldnames or []}
            try:
                contest_id = _clean(raw.get("Contest_ID"))
                party_id = _clean(raw.get("Party_ID"))
                if not contest_id or not party_id:
                    raise ValueError("Contest_ID and Party_ID are required")
                vote_text = (_clean(raw.get("Votes")) or "").replace(",", "")
                if not vote_text.isdigit():
                    raise ValueError("Votes must be a non-negative integer")
                vote_total = int(vote_text)
                parsed = {
                    "manifest_key": manifest.manifest_key,
                    "election_key": manifest.election_key,
                    "election_type": manifest.election_type,
                    "election_year": manifest.election_year,
                    "source_url": manifest.source_url,
                    "source_format": "csv",
                    "source_row_number": row_number,
                    "source_contest_id": contest_id,
                    "source_contest_name": _clean(raw.get("Contest_Name")),
                    "geography_level": manifest.geography_level,
                    "source_geography_id": _clean(raw.get("Province_ID")),
                    "source_geography_name": _clean(raw.get("Province_Name")),
                    "source_party_id": party_id,
                    "source_party_name": _clean(raw.get("Party_Name")),
                    "source_candidate_id": _clean(raw.get("Candidate_ID")),
                    "source_candidate_name": _clean(raw.get("Candidate_Name")),
                    "vote_total": vote_total,
                    "raw_row_json": preserved,
                    "row_checksum_sha256": _checksum(preserved),
                }
                parsed["result_key"] = result_key_for(manifest.manifest_key, parsed)
                rows.append(parsed)
            except (TypeError, ValueError) as exc:
                failures.append(
                    {"row_number": row_number, "error_type": type(exc).__name__, "error": str(exc)}
                )

    return {"rows": rows, "failures": failures, "input_rows": input_rows}
