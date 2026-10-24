import pytest

from political_bites.config import load_watchlist
from political_bites.db import connect, init_schema
from political_bites.provenance import record_run


@pytest.fixture
def con():
    c = connect(":memory:")
    init_schema(c)
    return c


def test_schema_is_idempotent(con):
    init_schema(con)
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert {"politician", "source_item", "clip", "clip_audio_features", "pipeline_run"} <= tables


def test_clip_defaults_are_private_and_pending(con):
    con.execute(
        "INSERT INTO clip (clip_id, source_id, start_s, end_s, license_tier) "
        "VALUES ('c1', 's1', 0, 3, 'A')"
    )
    row = con.execute("SELECT review_status, release_mode FROM clip").fetchone()
    assert row == ("pending", "private")


def test_record_run_success(con):
    with record_run(con, "smoke", tool="t", tool_version="1"):
        pass
    assert con.execute("SELECT status FROM pipeline_run").fetchone() == ("succeeded",)


def test_record_run_failure_is_logged_and_reraised(con):
    with pytest.raises(RuntimeError), record_run(con, "boom"):
        raise RuntimeError("nope")
    status, error = con.execute("SELECT status, error FROM pipeline_run").fetchone()
    assert status == "failed" and "nope" in error


def test_missing_watchlist_is_empty(tmp_path):
    assert load_watchlist(tmp_path / "missing.yaml") == []


def test_watchlist_loads(tmp_path):
    p = tmp_path / "w.yaml"
    p.write_text("politicians:\n  - politician_id: S000148\n    note: example\n", encoding="utf-8")
    assert [e.politician_id for e in load_watchlist(p)] == ["S000148"]


# Phase 0 shapes, before bioguide_id was renamed to politician_id.
_OLD_DDL = [
    "CREATE TABLE politician (bioguide_id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, "
    "party VARCHAR, state VARCHAR, chamber VARCHAR, url VARCHAR, notes VARCHAR)",
    "CREATE TABLE politician_term (bioguide_id VARCHAR NOT NULL, role VARCHAR, chamber VARCHAR, "
    "party VARCHAR, start_date DATE, end_date DATE, committees VARCHAR)",
    "CREATE TABLE source_speaker (source_id VARCHAR NOT NULL, diarization_label VARCHAR NOT NULL, "
    "bioguide_id VARCHAR, role VARCHAR, name VARCHAR, outlet VARCHAR, id_confidence DOUBLE, "
    "id_method VARCHAR)",
    "CREATE TABLE clip (clip_id VARCHAR PRIMARY KEY, source_id VARCHAR NOT NULL, "
    "bioguide_id VARCHAR, start_s DOUBLE NOT NULL, end_s DOUBLE NOT NULL, transcript VARCHAR, "
    "transcript_confidence DOUBLE, context_before VARCHAR, context_after VARCHAR, "
    "license_tier VARCHAR NOT NULL, review_status VARCHAR NOT NULL DEFAULT 'pending', "
    "release_mode VARCHAR NOT NULL DEFAULT 'private', raw_path VARCHAR, isolated_path VARCHAR, "
    "commentary_note VARCHAR)",
]


def test_phase0_database_is_migrated_with_data_preserved(tmp_path):
    import duckdb

    from political_bites.legislators import parse_people, upsert_people

    db = tmp_path / "phase0.duckdb"
    old = duckdb.connect(str(db))
    for stmt in _OLD_DDL:
        old.execute(stmt)
    old.execute("INSERT INTO politician (bioguide_id, name, party) VALUES ('O000172', 'AOC', 'D')")
    old.execute("INSERT INTO politician_term (bioguide_id, role) VALUES ('O000172', 'Rep')")
    old.execute(
        "INSERT INTO clip (clip_id, source_id, bioguide_id, start_s, end_s, license_tier) "
        "VALUES ('c1', 's1', 'O000172', 0, 2, 'A')"
    )
    old.close()

    c = connect(db)
    init_schema(c)
    init_schema(c)  # idempotent
    for table in ("politician", "politician_term", "source_speaker", "clip"):
        cols = {r[0] for r in c.execute(f"DESCRIBE {table}").fetchall()}
        assert "politician_id" in cols and "bioguide_id" not in cols, table
    assert c.execute("SELECT politician_id, name, party FROM politician").fetchone() == (
        "O000172",
        "AOC",
        "D",
    )
    assert c.execute("SELECT politician_id FROM politician_term").fetchone() == ("O000172",)
    assert c.execute("SELECT politician_id, review_status, release_mode FROM clip").fetchone() == (
        "O000172",
        "pending",
        "private",
    )
    # the loader that originally crashed now works on the migrated database
    people = parse_people(
        "- id: {bioguide: O000172}\n  name: {official_full: AOC}\n"
        "  terms:\n  - {type: rep, start: '2025-01-03', end: '2027-01-03', party: Democrat}\n"
    )
    assert upsert_people(c, people, ["O000172"]) == []
    assert c.execute("SELECT count(*) FROM politician").fetchone() == (1,)
