import pytest
import importlib
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models.committee import Committee
from app.models.committee_attendance import CommitteeAttendance
from app.models.committee_meeting import CommitteeMeeting
from app.models.committee_membership import CommitteeMembership
from app.models.ai_answer import AiAnswer
from app.models.parliamentary_question import ParliamentaryQuestion
from app.models.party import Party
from app.models.politician import Politician
from app.services.ai_service import RetrievedEvidence, _ask_openai, _clean_display_text, _clean_parliament_question_text

importlib.import_module("app.models")


client = TestClient(app)


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestingSessionLocal() as db:
        yield db
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def _ingest_eskom_question(monkeypatch, db_session):
    client.post("/ingest/seed")
    url = "https://www.parliament.gov.za/question/test-ai-eskom-001"
    html = """
    <html><body>
      <h1>Written question reply NW-AI-1 â Eskom maintenance</h1>
      <p>Question Number: NW-AI-1</p>
      <p>Asked By: Julius Malema</p>
      <p>Department: Electricity</p>
      <p>Status: Answered</p>
      <p>Question: Which Eskom substations require urgent maintenance?</p>
      <p>Answer: The department supplied a schedule of Eskom maintenance work.</p>
    </body></html>
    """
    monkeypatch.setattr("app.ingestion.parliament_questions.fetch_page", lambda _: html)
    response = client.post("/ingest/parliamentary-questions", json={"urls": [url]})
    assert response.status_code == 200
    return url


def _ingest_multiple_eskom_questions(monkeypatch, db_session):
    client.post("/ingest/seed")
    pages = {
        "https://www.parliament.gov.za/question/test-ai-dlamini-eskom": """
        <html><body>
          <h1>Written question reply NW1025 - Eskom maintenance</h1>
          <p>Question Number: NW1025</p>
          <p>Asked By: Ms M Dlamini (EFF)</p>
          <p>Department: Water and Sanitation</p>
          <p>Status: Answered</p>
          <p>Question: Whether Eskom substations require urgent maintenance?</p>
          <p>Answer: The department supplied an Eskom maintenance schedule.</p>
        </body></html>
        """,
        "https://www.parliament.gov.za/question/test-ai-tito-eskom": """
        <html><body>
          <h1>Written question reply NW1661 - Eskom school connection</h1>
          <p>Question Number: NW1661</p>
          <p>Asked By: Mrs L F Tito (EFF)</p>
          <p>Department: Basic Education</p>
          <p>Status: Answered</p>
          <p>Question: Whether Eskom has connected schools to electricity?</p>
          <p>Answer: The department reported on school electricity connections.</p>
        </body></html>
        """,
    }
    monkeypatch.setattr("app.ingestion.parliament_questions.fetch_page", lambda url: pages[url])
    response = client.post("/ingest/parliamentary-questions", json={"urls": list(pages)})
    assert response.status_code == 200


def test_ai_ask_returns_source_backed_answer_without_openai_key(monkeypatch, db_session):
    monkeypatch.setattr("app.services.ai_service.settings.ai_api_key", "")
    source_url = _ingest_eskom_question(monkeypatch, db_session)

    response = client.post("/ai/ask", json={"question": "Which MPs asked questions about Eskom?"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "questions"
    assert body["model_used"] == "deterministic-source-summary"
    assert body["cached"] is False
    assert "Eskom" in body["answer"]
    assert "The records include questions from Julius Malema" in body["answer"]
    assert "Relevant source-backed records:" in body["answer"]
    assert "NATIONAL ASSEMBLY QUESTION" not in body["answer"]
    assert "â" not in body["answer"]
    assert any(source["source_url"] == source_url for source in body["sources"])
    assert any(source["asked_by"] == "Julius Malema" for source in body["sources"])
    assert body["data_snapshot"]["parliamentary_questions"] >= 1
    assert body["data_snapshot"]["ai_answer_format_version"] == 20
    assert body["data_snapshot"]["openai_configured"] == 0


def test_ai_ask_filters_questions_by_named_mp_and_topic(monkeypatch, db_session):
    monkeypatch.setattr("app.services.ai_service.settings.ai_api_key", "")
    _ingest_multiple_eskom_questions(monkeypatch, db_session)

    response = client.post("/ai/ask", json={"question": "what did Ms M Dlamini (EFF) ask about eskom?"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "questions"
    assert "where Ms M Dlamini (EFF) asked about Eskom" in body["answer"]
    assert "Ms M Dlamini (EFF)" in body["answer"]
    assert "Mrs L F Tito" not in body["answer"]
    assert all("Dlamini" in f"{source.get('asked_by')} {source.get('excerpt')}" for source in body["sources"])
    assert all("Tito" not in f"{source.get('asked_by')} {source.get('excerpt')}" for source in body["sources"])
    assert all("Eskom" in f"{source['title']} {source.get('excerpt')}" for source in body["sources"])
    assert body["data_snapshot"]["ai_answer_format_version"] == 20


def test_ai_ask_routes_hearing_question_to_committee_meetings(monkeypatch, db_session):
    monkeypatch.setattr("app.services.ai_service.settings.ai_api_key", "")
    party = Party(name="Economic Freedom Fighters", short_name="EFF")
    db_session.add(party)
    db_session.flush()
    politician = Politician(
        full_name="Julius Sello Malema",
        display_name="J Malema",
        slug="j-malema",
        party_id=party.id,
        profile_url="https://www.pa.org.za/person/julius-sello-malema/",
        source_status="PA_VERIFIED",
    )
    db_session.add(politician)
    db_session.flush()
    meeting = CommitteeMeeting(
        title="Mkhwanazi Inquiry: Presentation of Evidentiary Report by Evidence Leaders",
        committee_name="Ad Hoc Committee to Investigate Allegations made by Lieutenant General Nhlanhla Mkhwanazi",
        summary=(
            "The Chairperson explained that the meeting would consider the evidentiary report. "
            "Mr Vhonani Ramaano, Committee Secretary, informed the Committee that apologies had been "
            "received from Mr Malema and Ms Mathys, who had indicated that they had prior commitments. "
            "The evidence leader then discussed the Political Killings Task Team and the transfer of 121 dockets."
        ),
        date=date(2026, 5, 28),
        source_url="https://pmg.org.za/committee-meeting/43160/",
    )
    db_session.add_all(
        [
            meeting,
            CommitteeMeeting(
                title="General Laws briefing",
                committee_name="Finance",
                summary="A general briefing on anti-money laundering laws.",
                source_url="https://pmg.org.za/committee-meeting/general-laws/",
            ),
        ]
    )
    db_session.flush()
    db_session.add(
        CommitteeAttendance(
            meeting_id=meeting.id,
            politician_id=politician.id,
            name_raw="Mr Malema",
            attendance_status="apology",
            source_url="https://pmg.org.za/committee-meeting/43160/",
        )
    )
    db_session.commit()

    response = client.post(
        "/ai/ask",
        json={"question": "what did julius malema ask in the Lieutenant General Nhlanhla Mkhwanazi hearing?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "hearings"
    assert body["model_used"] == "deterministic-source-summary"
    assert body["answer"].startswith("I could not find a source-backed record of Julius Malema asking a question")
    assert "recorded as apology in 1 meeting record" in body["answer"]
    assert "none of the imported text shows a question or intervention" in body["answer"]
    assert "Relevant PMG evidence about Julius Malema" in body["answer"]
    assert "Political Killings Task Team" in body["answer"]
    assert "parliamentary question" not in body["answer"].lower()
    assert body["sources"][0]["source_type"] == "person_meeting_evidence"
    assert body["sources"][0]["status"] is None
    assert body["sources"][0]["source_url"] == "https://pmg.org.za/committee-meeting/43160/"
    assert all(source["source_url"] != "https://pmg.org.za/committee-meeting/general-laws/" for source in body["sources"])
    assert body["data_snapshot"]["ai_answer_format_version"] == 20


def test_ai_ask_extracts_person_intervention_from_hearing(monkeypatch, db_session):
    monkeypatch.setattr("app.services.ai_service.settings.ai_api_key", "")
    db_session.add(
        CommitteeMeeting(
            title="SAPS corruption inquiry",
            committee_name="Police",
            summary=(
                "The Committee discussed police corruption allegations. "
                "Ms Dlamini asked whether suspended officials had access to case dockets. "
                "The Minister said the department would submit a written reply."
            ),
            date=date(2026, 6, 1),
            source_url="https://pmg.org.za/committee-meeting/saps-corruption/",
        )
    )
    db_session.commit()

    response = client.post(
        "/ai/ask",
        json={"question": "what did Ms Dlamini ask in the SAPS corruption hearing?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "hearings"
    assert body["answer"].startswith("I found source-backed PMG meeting text where Ms Dlamini")
    assert "asked whether suspended officials had access to case dockets" in body["answer"]
    assert body["sources"][0]["source_type"] == "person_meeting_evidence"
    assert body["data_snapshot"]["ai_answer_format_version"] == 20


def test_ai_question_evidence_text_is_cleaned_before_answering():
    raw = (
        "NATIONAL ASSEMBLY QUESTION 1025 NW1153E NATIONAL ASSEMBLY FOR WRITTEN REPLY "
        "QUESTION NO 1025 DATE OF PUBLICATION IN INTERNAL QUESTION PAPER: 06 MARCH 2026 "
        "1025. Ms M Dlamini (EFF) to ask the Minister of Water and Sanitation: "
        "Whether Eskom substations require urgent maintenance?"
    )

    cleaned = _clean_parliament_question_text(raw, "Ms M Dlamini (EFF)")

    assert cleaned is not None
    assert cleaned.startswith("asked the Minister of Water and Sanitation")
    assert "NATIONAL ASSEMBLY QUESTION" not in cleaned
    assert "to ask the Ministe..." not in cleaned


def test_ai_display_text_cleans_common_mojibake():
    assert _clean_display_text("Ethics and Membersâ Interest") == "Ethics and Members' Interest"
    assert _clean_display_text("Ethics and Members’ Interest") == "Ethics and Members' Interest"
    assert _clean_display_text("Question Ã¢ÂÂ reply") == "Question - reply"


    assert _clean_display_text("Juliusâ¯Malema â source ãsourceã") == "Julius Malema - source"


    assert _clean_display_text("Anti-Money Launderingâ¦ briefing") == "Anti-Money Laundering... briefing"


def test_ai_ask_uses_openai_when_configured(monkeypatch):
    class FakeResponse:
        is_success = True
        status_code = 200
        text = ""

        def json(self):
            return {"output_text": "J Malema is described by source-backed records."}

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("app.services.ai_service.settings.ai_api_key", "  'test-key'  ")
    monkeypatch.setattr("app.services.ai_service.settings.ai_model", "gpt-test")
    monkeypatch.setattr("app.services.ai_service.httpx.Client", FakeClient)

    answer, model_used = _ask_openai(
        "who is julius malema?",
        RetrievedEvidence(intent="profile", sources=[{"title": "J Malema"}], coverage_notice=""),
        "fallback",
    )

    assert answer == "J Malema is described by source-backed records."
    assert model_used == "gpt-test"


def test_ai_ask_falls_back_to_chat_completions_when_responses_fails(monkeypatch):
    class FakeResponse:
        def __init__(self, status_code, body):
            self.status_code = status_code
            self._body = body
            self.is_success = status_code < 400
            self.text = str(body)

        def json(self):
            return self._body

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, url, *args, **kwargs):
            if url.endswith("/responses"):
                return FakeResponse(400, {"error": "not supported"})
            return FakeResponse(200, {"choices": [{"message": {"content": "J Malema chat fallback answer."}}]})

    monkeypatch.setattr("app.services.ai_service.settings.ai_api_key", "test-key")
    monkeypatch.setattr("app.services.ai_service.settings.ai_model", "gpt-test")
    monkeypatch.setattr("app.services.ai_service.httpx.Client", FakeClient)

    answer, model_used = _ask_openai(
        "who is julius malema?",
        RetrievedEvidence(intent="profile", sources=[{"title": "J Malema"}], coverage_notice=""),
        "fallback",
    )

    assert answer == "J Malema chat fallback answer."
    assert model_used == "gpt-test"


def test_ai_ask_uses_chat_directly_for_openai_compatible_providers(monkeypatch):
    seen = {"urls": [], "headers": []}

    class FakeResponse:
        is_success = True
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": "J Malema OpenRouter answer."}}]}

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, url, *args, **kwargs):
            seen["urls"].append(url)
            seen["headers"].append(kwargs["headers"])
            return FakeResponse()

    monkeypatch.setattr("app.services.ai_service.settings.ai_api_key", "test-key")
    monkeypatch.setattr("app.services.ai_service.settings.ai_model", "openrouter/free-model")
    monkeypatch.setattr("app.services.ai_service.settings.ai_base_url", "https://openrouter.ai/api/v1")
    monkeypatch.setattr("app.services.ai_service.settings.ai_app_url", "https://knowyourmpza.vercel.app")
    monkeypatch.setattr("app.services.ai_service.httpx.Client", FakeClient)

    answer, model_used = _ask_openai(
        "who is julius malema?",
        RetrievedEvidence(intent="profile", sources=[{"title": "J Malema"}], coverage_notice=""),
        "fallback",
    )

    assert answer == "J Malema OpenRouter answer."
    assert model_used == "openrouter/free-model"
    assert seen["urls"] == ["https://openrouter.ai/api/v1/chat/completions"]
    assert seen["headers"][0]["HTTP-Referer"] == "https://knowyourmpza.vercel.app"
    assert seen["headers"][0]["X-Title"] == "KnowYourMPZA"


def test_ai_ask_rejects_unfaithful_provider_answer(monkeypatch):
    class FakeResponse:
        is_success = True
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": "Only Hc Kruger asked about Eskom."}}]}

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("app.services.ai_service.settings.ai_api_key", "test-key")
    monkeypatch.setattr("app.services.ai_service.settings.ai_model", "openrouter/free")
    monkeypatch.setattr("app.services.ai_service.settings.ai_base_url", "https://openrouter.ai/api/v1")
    monkeypatch.setattr("app.services.ai_service.httpx.Client", FakeClient)
    fallback = (
        "I found 8 imported parliamentary question records mentioning Eskom. "
        "The records include questions from Ms M Dlamini (EFF), Mr T S Mjadu (MK), and Hc Kruger."
    )

    answer, model_used = _ask_openai(
        "Which MPs asked questions about Eskom?",
        RetrievedEvidence(
            intent="questions",
            sources=[
                {"asked_by": "Ms M Dlamini (EFF)", "title": "NW1025"},
                {"asked_by": "Mr T S Mjadu (MK)", "title": "NW3636"},
                {"asked_by": "Hc Kruger", "title": "NW3164"},
                {"asked_by": None, "title": "CW688"},
                {"asked_by": None, "title": "NW3411"},
                {"asked_by": None, "title": "NW613"},
                {"asked_by": None, "title": "NW614"},
                {"asked_by": None, "title": "NW615"},
            ],
            coverage_notice="Questions are still backfilling.",
        ),
        fallback,
    )

    assert answer == fallback
    assert model_used == "deterministic-source-summary"


def test_ai_ask_rejects_profile_answer_with_changed_committee_name(monkeypatch):
    class FakeResponse:
        is_success = True
        status_code = 200
        text = ""

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                "Julius Malema serves on the Ad Hoc Committee to Investigate Allegations made "
                                "by Lieutenant General Nhlanhla Mkhwanzi."
                            )
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("app.services.ai_service.settings.ai_api_key", "test-key")
    monkeypatch.setattr("app.services.ai_service.settings.ai_model", "openrouter/free")
    monkeypatch.setattr("app.services.ai_service.settings.ai_base_url", "https://openrouter.ai/api/v1")
    monkeypatch.setattr("app.services.ai_service.httpx.Client", FakeClient)
    fallback = (
        "J Malema is a South African public representative in the KnowYourMPZA records.\n\n"
        "Linked committee work: Ad Hoc Committee to Investigate Allegations made by Lieutenant General Nhlanhla Mkhwanazi - Member."
    )

    answer, model_used = _ask_openai(
        "who is julius malema?",
        RetrievedEvidence(
            intent="profile",
            sources=[
                {
                    "title": "J Malema",
                    "display_name": "J Malema",
                    "committees": [
                        "Ad Hoc Committee to Investigate Allegations made by Lieutenant General Nhlanhla Mkhwanazi - Member"
                    ],
                }
            ],
            coverage_notice="Profile records are source-backed.",
        ),
        fallback,
    )

    assert answer == fallback
    assert model_used == "deterministic-source-summary"


def test_ai_ask_who_is_resolves_profile_without_near_name_noise(db_session, monkeypatch):
    monkeypatch.setattr("app.services.ai_service.settings.ai_api_key", "")
    eff = Party(name="Economic Freedom Fighters", short_name="EFF")
    unknown = Party(name="Unknown", short_name="UNKNOWN")
    db_session.add_all([eff, unknown])
    db_session.flush()
    db_session.add_all(
        [
            Politician(
                full_name="Julius Sello Malema",
                display_name="J Malema",
                slug="j-malema",
                party_id=eff.id,
                profile_url="https://www.pa.org.za/person/julius-sello-malema/",
                source_status="PA_VERIFIED",
            ),
            Politician(
                full_name="C N Malematja",
                display_name="C Malematja",
                slug="c-malematja",
                party_id=unknown.id,
                profile_url="https://example.test/c-malematja",
                source_status="PMG_DERIVED",
            ),
        ]
    )
    db_session.commit()

    response = client.post("/ai/ask", json={"question": "who is julius malema"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "profile"
    assert "J Malema is a South African public representative" in body["answer"]
    assert "Party: EFF" in body["answer"]
    assert "C Malematja" not in body["answer"]
    assert "Written question" not in body["answer"]
    assert body["sources"] == [
        {
            "title": "J Malema",
            "source_url": "https://www.pa.org.za/person/julius-sello-malema/",
            "source_type": "politician_profile",
            "record_id": body["sources"][0]["record_id"],
            "date": None,
            "excerpt": "Julius Sello Malema | Party: EFF | Linked parliamentary questions: 0 | Linked attendance records: 0 | PA_VERIFIED",
            "asked_by": None,
            "department": None,
            "status": None,
        }
    ]
    assert body["data_snapshot"]["ai_answer_format_version"] == 20


def test_ai_ask_who_sits_on_committee_lists_members(db_session, monkeypatch):
    monkeypatch.setattr("app.services.ai_service.settings.ai_api_key", "")
    party = Party(name="African National Congress", short_name="ANC")
    db_session.add(party)
    db_session.flush()
    politician = Politician(
        full_name="Example Police Member",
        display_name="E Police",
        slug="e-police",
        party_id=party.id,
        profile_url="https://example.test/e-police",
        source_status="TEST",
    )
    committee = Committee(
        name="Police",
        slug="police",
        source_url="https://example.test/committee/police",
    )
    db_session.add_all([politician, committee])
    db_session.flush()
    db_session.add(
        CommitteeMembership(
            politician_id=politician.id,
            committee_id=committee.id,
            role="Member",
            source_url="https://example.test/committee/police",
        )
    )
    db_session.commit()

    response = client.post("/ai/ask", json={"question": "Who sits on the police committee?"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "committees"
    assert "linked member record" in body["answer"]
    assert "E Police (ANC, Member)" in body["answer"]
    assert "Agriculture" not in body["answer"]


def test_ai_ask_counts_and_names_party_members(db_session, monkeypatch):
    monkeypatch.setattr("app.services.ai_service.settings.ai_api_key", "")
    eff = Party(name="Economic Freedom Fighters", short_name="EFF", source_url="https://example.test/party/eff")
    anc = Party(name="African National Congress", short_name="ANC", source_url="https://example.test/party/anc")
    db_session.add_all([eff, anc])
    db_session.flush()
    db_session.add_all(
        [
            Politician(
                full_name="Julius Sello Malema",
                display_name="J Malema",
                slug="j-malema-party",
                party_id=eff.id,
                profile_url="https://example.test/j-malema",
                source_status="PA_VERIFIED",
            ),
            Politician(
                full_name="Mbuyiseni Ndlozi",
                display_name="M Ndlozi",
                slug="m-ndlozi",
                party_id=eff.id,
                profile_url="https://example.test/m-ndlozi",
                source_status="PA_VERIFIED",
            ),
            Politician(
                full_name="Example ANC Member",
                display_name="E ANC",
                slug="e-anc",
                party_id=anc.id,
                profile_url="https://example.test/e-anc",
                source_status="PA_VERIFIED",
            ),
        ]
    )
    db_session.commit()

    response = client.post("/ai/ask", json={"question": "can you tell how many people are members of the EFF and name them?"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "parties"
    assert body["model_used"] == "deterministic-source-summary"
    assert "I found 2 imported politician records directly linked to EFF." in body["answer"]
    assert "J Malema" in body["answer"]
    assert "M Ndlozi" in body["answer"]
    assert "E ANC" not in body["answer"]
    assert body["sources"][0]["source_type"] == "party_member_summary"
    assert body["sources"][0]["source_url"] == "https://example.test/party/eff"
    assert body["data_snapshot"]["ai_answer_format_version"] == 20


def test_ai_ask_uses_party_labeled_question_names_when_party_links_missing(db_session, monkeypatch):
    monkeypatch.setattr("app.services.ai_service.settings.ai_api_key", "")
    eff = Party(name="Economic Freedom Fighters", short_name="EFF", source_url="https://example.test/party/eff")
    db_session.add(eff)
    db_session.flush()
    db_session.add_all(
        [
            ParliamentaryQuestion(
                title="Written question NW1025",
                question_number="NW1025",
                asked_by_name="Ms M Dlamini (EFF)",
                question_text="Question about Eskom maintenance.",
                source_url="https://example.test/questions/nw1025",
            ),
            ParliamentaryQuestion(
                title="Written question NW1637",
                question_number="NW1637",
                asked_by_name="Ms M Dlamini (EFF)",
                question_text="Another question from the same MP.",
                source_url="https://example.test/questions/nw1637",
            ),
            ParliamentaryQuestion(
                title="Written question NW1661",
                question_number="NW1661",
                asked_by_name="Mrs L F Tito (EFF)",
                question_text="Question about schools.",
                source_url="https://example.test/questions/nw1661",
            ),
        ]
    )
    db_session.commit()

    response = client.post("/ai/ask", json={"question": "can you tell how many people are members of the EFF and name them?"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "parties"
    assert "2 source-backed person records labeled as EFF" in body["answer"]
    assert "none are directly linked to the party table yet" in body["answer"]
    assert "Ms M Dlamini" in body["answer"]
    assert "Mrs L F Tito" in body["answer"]
    assert "parliamentary question party label" in body["answer"]
    assert "PARLIAMENTARY_QUESTION_PARTY_LABEL" not in body["answer"]
    assert body["sources"][0]["source_type"] == "party_member_summary"
    assert body["data_snapshot"]["ai_answer_format_version"] == 20


def test_ai_ask_reuses_saved_answer_when_snapshot_is_unchanged(monkeypatch, db_session):
    monkeypatch.setattr("app.services.ai_service.settings.ai_api_key", "")
    _ingest_eskom_question(monkeypatch, db_session)

    first = client.post("/ai/ask", json={"question": "Which MPs asked questions about Eskom?"})
    second = client.post("/ai/ask", json={"question": "Which MPs asked questions about Eskom?"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["cached"] is True
    count = db_session.scalar(
        select(func.count()).select_from(AiAnswer).where(AiAnswer.normalized_question == "which mps asked questions about eskom?")
    )
    assert count == 1


def test_ai_ask_refresh_regenerates_saved_answer(monkeypatch, db_session):
    monkeypatch.setattr("app.services.ai_service.settings.ai_api_key", "")
    _ingest_eskom_question(monkeypatch, db_session)

    first = client.post("/ai/ask", json={"question": "Which MPs asked questions about Eskom?"})
    refreshed = client.post("/ai/ask", json={"question": "Which MPs asked questions about Eskom?", "refresh": True})

    assert first.status_code == 200
    assert refreshed.status_code == 200
    assert first.json()["id"] == refreshed.json()["id"]
    assert refreshed.json()["cached"] is False
