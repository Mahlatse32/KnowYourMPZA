from scripts.ingest_all_parliamentary_questions import _prioritize_new_urls


def test_parliament_question_backfill_prefers_new_urls_before_refreshing_existing():
    urls = [
        "https://www.parliament.gov.za/storage/app/media/Docs/exe_rq_na/existing-a.pdf",
        "https://www.parliament.gov.za/storage/app/media/Docs/exe_rq_na/new-b.pdf",
        "https://www.parliament.gov.za/storage/app/media/Docs/exe_rq_na/new-a.pdf",
        "https://www.parliament.gov.za/storage/app/media/Docs/exe_rq_na/existing-b.pdf",
    ]
    existing = {
        "https://www.parliament.gov.za/storage/app/media/Docs/exe_rq_na/existing-a.pdf",
        "https://www.parliament.gov.za/storage/app/media/Docs/exe_rq_na/existing-b.pdf",
    }

    selected = _prioritize_new_urls(urls, existing, limit=3)

    assert selected == [
        "https://www.parliament.gov.za/storage/app/media/Docs/exe_rq_na/new-a.pdf",
        "https://www.parliament.gov.za/storage/app/media/Docs/exe_rq_na/new-b.pdf",
        "https://www.parliament.gov.za/storage/app/media/Docs/exe_rq_na/existing-a.pdf",
    ]


def test_parliament_question_backfill_deduplicates_candidates():
    urls = [
        "https://www.parliament.gov.za/storage/app/media/Docs/exe_rq_na/new-a.pdf",
        "https://www.parliament.gov.za/storage/app/media/Docs/exe_rq_na/new-a.pdf",
    ]

    assert _prioritize_new_urls(urls, set(), limit=None) == [
        "https://www.parliament.gov.za/storage/app/media/Docs/exe_rq_na/new-a.pdf"
    ]
