import pytest

from political_bites.db import connect, init_schema
from political_bites.legislators import parse_people, person_key, upsert_people

MEMBERS = """
- id: {bioguide: X000001, wikidata: Q1}
  name: {first: Ada, last: Lovelace, official_full: Ada Lovelace}
  terms:
  - {type: rep, start: '2019-01-03', end: '2021-01-03', state: NY, district: 1, party: Democrat}
  - {type: sen, start: '2021-01-03', end: '2027-01-03', state: NY, party: Independent}
"""
EXEC = """
- id: {wikidata: Q22686, cspan: 20967}
  name: {first: Donald, last: Trump}
  terms:
  - {type: prez, start: '2017-01-20', end: '2021-01-20', party: Republican}
"""


@pytest.fixture
def con():
    c = connect(":memory:")
    init_schema(c)
    return c


def test_person_keys():
    assert person_key({"id": {"bioguide": "A1", "wikidata": "Q9"}}) == "A1"
    assert person_key({"id": {"wikidata": "Q9"}}) == "wd:Q9"
    assert person_key({"id": {}}) is None


def test_upsert_keeps_party_per_term(con):
    index = parse_people(MEMBERS)
    assert upsert_people(con, index, ["X000001"]) == []
    parties = con.execute("SELECT role, party FROM politician_term ORDER BY start_date").fetchall()
    assert parties == [("Representative", "Democrat"), ("Senator", "Independent")]
    assert con.execute("SELECT chamber, party FROM politician").fetchone() == (
        "senate",
        "Independent",
    )


def test_executive_has_wikidata_key_and_external_ids(con):
    index = parse_people(EXEC)
    upsert_people(con, index, ["wd:Q22686"])
    name, chamber, ext = con.execute(
        "SELECT name, chamber, external_ids FROM politician"
    ).fetchone()
    assert (name, chamber) == ("Donald Trump", "executive")
    assert '"cspan": 20967' in ext


def test_upsert_is_idempotent_and_reports_missing(con):
    index = parse_people(MEMBERS)
    upsert_people(con, index, ["X000001"])
    missing = upsert_people(con, index, ["X000001", "Z999999"])
    assert missing == ["Z999999"]
    assert con.execute("SELECT count(*) FROM politician").fetchone() == (1,)
    assert con.execute("SELECT count(*) FROM politician_term").fetchone() == (2,)
