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
