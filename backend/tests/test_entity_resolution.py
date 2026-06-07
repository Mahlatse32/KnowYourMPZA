from app.db import SessionLocal
from app.models.party import Party
from app.models.politician import Politician
from app.models.politician_alias import PoliticianAlias
from app.services.entity_resolution import resolve_politician_name


def test_entity_resolution_alias_and_unique_surname():
    with SessionLocal() as db:
        party = db.query(Party).filter_by(short_name="TEST").first()
        if party is None:
            party = Party(name="Test Party", short_name="TEST")
            db.add(party)
            db.flush()
        politician = db.query(Politician).filter_by(slug="resolution-test-person").first()
        if politician is None:
            politician = Politician(
                full_name="Resolution Test Person",
                display_name="Resolution Person",
                slug="resolution-test-person",
                party=party,
            )
            db.add(politician)
            db.flush()
        if not db.query(PoliticianAlias).filter_by(politician=politician, alias="Hon Person").first():
            db.add(PoliticianAlias(politician=politician, alias="Hon Person", alias_type="hon_surname"))
        db.commit()

        alias_match = resolve_politician_name(db, "Hon Person")
        surname_match = resolve_politician_name(db, "Person")

        assert alias_match is not None
        assert alias_match.politician.id == politician.id
        assert surname_match is not None
        assert surname_match.match_reason == "unique_surname"
