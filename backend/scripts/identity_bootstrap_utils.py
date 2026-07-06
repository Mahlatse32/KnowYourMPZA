from app.services.identity_bootstrap_service import (
    bootstrap_identities_from_pmg,
    estimate_pmg_identity_bootstrap_attempts,
)
from app.services.ingestion_run_service import finish_ingestion_run, start_ingestion_run


def run_pmg_identity_bootstrap(db) -> dict:
    attempted = estimate_pmg_identity_bootstrap_attempts(db)
    run = start_ingestion_run(db, "PMG", "pmg_identity_bootstrap", attempted)
    try:
        result = bootstrap_identities_from_pmg(db)
    except Exception as exc:
        finish_ingestion_run(
            db,
            run,
            {
                "processed_count": 0,
                "created_count": 0,
                "updated_count": 0,
                "skipped_count": 0,
                "failed_count": 1,
                "errors": [{"url": "pmg_identity_bootstrap", "type": exc.__class__.__name__, "error": str(exc)}],
            },
        )
        raise

    created = (
        result["sources_created"]
        + result["parties_created"]
        + result["committees_created"]
        + result["politicians_created"]
        + result["aliases_created"]
        + result["memberships_created"]
        + result["question_mentions_created"]
    )
    updated = (
        result["committees_updated"]
        + result["politicians_updated"]
        + result.get("politicians_party_enriched", 0)
        + result["meetings_linked"]
        + result["attendance_linked"]
        + result["questions_linked"]
        + result["vote_events_linked"]
    )
    finish_ingestion_run(
        db,
        run,
        {
            "processed_count": attempted,
            "created_count": created,
            "updated_count": updated,
            "skipped_count": 0,
            "failed_count": 0,
            "errors": [],
        },
    )
    return {"attempted_count": attempted, **result}
