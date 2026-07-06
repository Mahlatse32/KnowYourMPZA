from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.models.committee_attendance import CommitteeAttendance
from app.models.committee_meeting import CommitteeMeeting
from app.models.party import Party
from app.models.politician import Politician
from app.services.accountability_service import (
    _resolve_or_create_party,
    upsert_committee_meeting,
)
from app.services.identity_bootstrap_service import bootstrap_identities_from_pmg


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def _meeting_payload(url: str, attendance: list[dict]) -> dict:
    return {
        "title": "Portfolio Committee on Energy: briefing",
        "date": date(2026, 1, 20),
        "source_url": url,
        "attendance": attendance,
    }


def test_resolve_or_create_party_creates_once_and_normalizes_variants(db):
    first = _resolve_or_create_party(db, "African National Congress", "https://pmg.org.za/committee-meeting/1/")
    again = _resolve_or_create_party(db, "ANC")

    assert first is not None
    assert again is not None
    assert first.id == again.id
    assert first.name == "African National Congress"
    assert first.short_name == "ANC"
    assert first.source_url == "https://pmg.org.za/committee-meeting/1/"
    assert db.scalar(select(Party).where(Party.short_name == "ANC")) is not None
    assert len(list(db.scalars(select(Party)))) == 1


def test_resolve_or_create_party_never_fabricates_unknown(db):
    assert _resolve_or_create_party(db, None) is None
    assert _resolve_or_create_party(db, "") is None
    assert _resolve_or_create_party(db, "Unknown") is None
    assert list(db.scalars(select(Party))) == []


def test_attendance_upsert_creates_party_and_links_row(db):
    url = "https://pmg.org.za/committee-meeting/party-test/"
    upsert_committee_meeting(
        db,
        _meeting_payload(
            url,
            [
                {
                    "name_raw": "Zungula, Mr V",
                    "party_name": "African Transformation Movement (ATM)",
                    "attendance_status": "present",
                    "confidence": 1.0,
                    "source_url": url,
                }
            ],
        ),
    )

    party = db.scalar(select(Party).where(Party.short_name == "ATM"))
    assert party is not None
    assert party.name == "African Transformation Movement"
    row = db.scalar(select(CommitteeAttendance))
    assert row.party_id == party.id

    # Re-ingesting the same meeting neither duplicates the party nor the row.
    upsert_committee_meeting(
        db,
        _meeting_payload(
            url,
            [
                {
                    "name_raw": "Zungula, Mr V",
                    "party_name": "ATM",
                    "attendance_status": "present",
                    "source_url": url,
                }
            ],
        ),
    )
    assert len(list(db.scalars(select(Party)))) == 1
    assert len(list(db.scalars(select(CommitteeAttendance)))) == 1


def test_attendance_reingest_heals_rows_missing_party(db):
    url = "https://pmg.org.za/committee-meeting/heal-test/"
    upsert_committee_meeting(
        db,
        _meeting_payload(
            url,
            [{"name_raw": "Dhlamini, Mr MG", "attendance_status": "present", "source_url": url}],
        ),
    )
    row = db.scalar(select(CommitteeAttendance))
    assert row.party_id is None

    upsert_committee_meeting(
        db,
        _meeting_payload(
            url,
            [
                {
                    "name_raw": "Dhlamini, Mr MG",
                    "party_name": "EFF",
                    "attendance_status": "present",
                    "source_url": url,
                }
            ],
        ),
    )
    row = db.scalar(select(CommitteeAttendance))
    party = db.scalar(select(Party).where(Party.short_name == "EFF"))
    assert party is not None
    assert row.party_id == party.id


def test_bootstrap_assigns_unambiguous_party_to_unknown_politicians(db):
    url = "https://pmg.org.za/committee-meeting/bootstrap-party/"
    upsert_committee_meeting(
        db,
        _meeting_payload(
            url,
            [
                {
                    "name_raw": "Zungula, Mr V",
                    "party_name": "ANC",
                    "attendance_status": "present",
                    "source_url": url,
                }
            ],
        ),
    )

    # First bootstrap creates the politician directly with the explicit party.
    summary = bootstrap_identities_from_pmg(db)
    assert summary["politicians_created"] == 1
    politician = db.scalar(select(Politician))
    assert politician.party.short_name == "ANC"

    # Second bootstrap is idempotent and does not flip the party.
    summary = bootstrap_identities_from_pmg(db)
    assert summary["politicians_created"] == 0
    db.refresh(politician)
    assert politician.party.short_name == "ANC"


def test_bootstrap_enriches_existing_unknown_party_politician(db):
    url = "https://pmg.org.za/committee-meeting/enrich-existing/"
    # Politician exists from an earlier bootstrap without party data.
    upsert_committee_meeting(
        db,
        _meeting_payload(
            url,
            [{"name_raw": "Botes, Mr W", "attendance_status": "present", "source_url": url}],
        ),
    )
    bootstrap_identities_from_pmg(db)
    politician = db.scalar(select(Politician))
    assert politician.party.short_name == "UNKNOWN"

    # A later sweep sees the explicit party for the same person.
    upsert_committee_meeting(
        db,
        _meeting_payload(
            url,
            [
                {
                    "name_raw": "Botes, Mr W",
                    "party_name": "Democratic Alliance",
                    "attendance_status": "present",
                    "source_url": url,
                }
            ],
        ),
    )
    summary = bootstrap_identities_from_pmg(db)
    assert summary["politicians_party_enriched"] == 1
    db.refresh(politician)
    assert politician.party.short_name == "DA"


def test_bootstrap_leaves_ambiguous_party_data_unassigned(db):
    urls = [
        "https://pmg.org.za/committee-meeting/ambiguous-1/",
        "https://pmg.org.za/committee-meeting/ambiguous-2/",
    ]
    for url, party_name in zip(urls, ["ANC", "EFF"]):
        upsert_committee_meeting(
            db,
            _meeting_payload(
                url,
                [
                    {
                        "name_raw": "Mokoena, Mr T",
                        "party_name": party_name,
                        "attendance_status": "present",
                        "source_url": url,
                    }
                ],
            ),
        )

    summary = bootstrap_identities_from_pmg(db)
    assert summary["politicians_party_enriched"] == 0
    politician = db.scalar(select(Politician))
    assert politician.party.short_name == "UNKNOWN"


def test_bootstrap_never_overwrites_a_real_party(db):
    url = "https://pmg.org.za/committee-meeting/no-overwrite/"
    upsert_committee_meeting(
        db,
        _meeting_payload(
            url,
            [
                {
                    "name_raw": "Malema, Mr J",
                    "party_name": "EFF",
                    "attendance_status": "present",
                    "source_url": url,
                }
            ],
        ),
    )
    bootstrap_identities_from_pmg(db)
    politician = db.scalar(select(Politician))
    assert politician.party.short_name == "EFF"

    # Conflicting later source data must not flip an assigned real party.
    upsert_committee_meeting(
        db,
        _meeting_payload(
            "https://pmg.org.za/committee-meeting/no-overwrite-2/",
            [
                {
                    "name_raw": "Malema, Mr J",
                    "party_name": "ANC",
                    "attendance_status": "present",
                    "source_url": url,
                }
            ],
        ),
    )
    summary = bootstrap_identities_from_pmg(db)
    assert summary["politicians_party_enriched"] == 0
    db.refresh(politician)
    assert politician.party.short_name == "EFF"
