import json
import wave
from datetime import datetime

import duckdb
import pytest

from political_bites.db import connect, init_schema
from political_bites.ingest import (
    IngestError,
    detect_caption_type,
    find_media_folders,
    ingest_folder,
    parse_vtt,
)
from political_bites.licensing import LicenseTier

ROLLING_VTT = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:03.000 align:start position:0%
the House will<00:00:01.500><c> come to</c><00:00:02.000><c> order</c>

00:00:03.000 --> 00:00:03.010 align:start position:0%
the House will come to order

00:00:03.010 --> 00:00:05.000 align:start position:0%
the House will come to order
the gentlewoman from New York

00:00:05.000 --> 00:00:07.000 align:start position:0%
the gentlewoman from New York
is recognized &amp; may proceed
"""


def make_wav(path, seconds=1, rate=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * rate * seconds)


def make_folder(root, name="20260721_abc123", *, captions=True, info=True):
    d = root / name
    d.mkdir(parents=True)
    make_wav(d / "source.wav")
    if captions:
        (d / "source.en.vtt").write_text(ROLLING_VTT, encoding="utf-8")
    if info:
        (d / "source.info.json").write_text(
            json.dumps(
                {
                    "id": "abc123",
                    "extractor_key": "Youtube",
                    "title": "House Floor Proceedings",
                    "channel": "Example Channel",
                    "channel_id": "UC123",
                    "webpage_url": "https://example.test/watch?v=abc123",
                    "upload_date": "20260721",
                    "duration": 1.0,
                    "subtitles": {},
                    "automatic_captions": {"en": [{"ext": "vtt"}]},
                }
            ),
            encoding="utf-8",
        )
    return d


@pytest.fixture
def con():
    c = connect(":memory:")
    init_schema(c)
    return c


def test_parse_vtt_strips_tags_and_rolling_duplicates():
    cues = parse_vtt(ROLLING_VTT)
    assert [c.text for c in cues] == [
        "the House will come to order",
        "the gentlewoman from New York",
        "is recognized & may proceed",
    ]
    assert cues[0].start_s == 1.0 and cues[2].end_s == 7.0


def test_parse_vtt_handles_hour_timestamps_and_empty_input():
    cues = parse_vtt("WEBVTT\n\n01:02:03.500 --> 01:02:05.000\nhello\n")
    assert cues[0].start_s == pytest.approx(3723.5)
    assert parse_vtt("") == []


def test_detect_caption_type():
    assert detect_caption_type({"subtitles": {"en": [1]}}) == "uploaded"
    assert detect_caption_type({"automatic_captions": {"en": [1]}}) == "auto"
    assert detect_caption_type({}) is None


def test_ingest_creates_source_and_captions(con, tmp_path):
    d = make_folder(tmp_path)
    sid = ingest_folder(con, d, tier=LicenseTier.A, event_type="floor", event_date="2026-07-21")
    assert sid == "youtube:abc123"
    row = con.execute(
        "SELECT platform, organization, license_tier, event_type, event_at, published_at, "
        "caption_type, duration_s, channel_id FROM source_item"
    ).fetchone()
    assert row[:4] == ("youtube", "Example Channel", "A", "floor")
    assert row[4] == datetime(2026, 7, 21) and row[5] == datetime(2026, 7, 21)
    assert row[6] == "auto" and row[7] == pytest.approx(1.0, abs=0.1) and row[8] == "UC123"
    assert con.execute("SELECT count(*) FROM source_caption").fetchone() == (3,)
    assert con.execute("SELECT status FROM pipeline_run").fetchone() == ("succeeded",)


def test_default_tier_is_strictest(con, tmp_path):
    ingest_folder(con, make_folder(tmp_path))
    assert con.execute("SELECT license_tier FROM source_item").fetchone() == ("C",)


def test_ingest_is_idempotent(con, tmp_path):
    d = make_folder(tmp_path)
    ingest_folder(con, d)
    ingest_folder(con, d)
    assert con.execute("SELECT count(*) FROM source_item").fetchone() == (1,)
    assert con.execute("SELECT count(*) FROM source_caption").fetchone() == (3,)


def test_ingest_without_info_or_captions_uses_hash_id(con, tmp_path):
    d = make_folder(tmp_path, captions=False, info=False)
    sid = ingest_folder(con, d)
    assert sid.startswith("local:")
    assert con.execute("SELECT platform, caption_type FROM source_item").fetchone() == (
        "local",
        None,
    )


def test_missing_or_ambiguous_audio_errors(con, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(IngestError, match="No audio"):
        ingest_folder(con, empty)
    d = make_folder(tmp_path, "two")
    make_wav(d / "other.wav")
    (d / "source.wav").rename(d / "a.wav")
    with pytest.raises(IngestError, match="Multiple audio"):
        ingest_folder(con, d)


def test_bad_date_is_rejected(con, tmp_path):
    with pytest.raises(IngestError, match="Unrecognized date"):
        ingest_folder(con, make_folder(tmp_path), event_date="07/21/2026")


def test_find_media_folders_parent_and_single(tmp_path):
    a = make_folder(tmp_path, "a")
    b = make_folder(tmp_path, "b")
    (tmp_path / "notes").mkdir()
    assert find_media_folders(tmp_path) == [a, b]
    assert find_media_folders(a) == [a]


def test_migration_upgrades_a_pre_existing_database(tmp_path):
    db = tmp_path / "old.duckdb"
    old = duckdb.connect(str(db))
    old.execute(
        "CREATE TABLE source_item (source_id VARCHAR PRIMARY KEY, platform VARCHAR NOT NULL, "
        "organization VARCHAR, url VARCHAR, title VARCHAR, published_at TIMESTAMP, "
        "event_at TIMESTAMP, event_type VARCHAR, license_tier VARCHAR NOT NULL, "
        "retrieved_at TIMESTAMP, file_hash VARCHAR, audio_fingerprint VARCHAR)"
    )
    old.close()
    c = connect(db)
    init_schema(c)
    init_schema(c)  # idempotent
    cols = {r[0] for r in c.execute("DESCRIBE source_item").fetchall()}
    assert {"media_path", "duration_s", "caption_type", "channel_id"} <= cols


def test_reingest_keeps_tier_and_event_info_unless_overridden(con, tmp_path):
    d = make_folder(tmp_path)
    ingest_folder(con, d, tier=LicenseTier.A, event_type="floor", event_date="2026-07-21")
    ingest_folder(con, d)
    row = con.execute("SELECT license_tier, event_type, event_at FROM source_item").fetchone()
    assert row == ("A", "floor", datetime(2026, 7, 21))
    ingest_folder(con, d, tier=LicenseTier.B)
    assert con.execute("SELECT license_tier FROM source_item").fetchone() == ("B",)


def test_cli_ingest_local_exit_codes(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from political_bites.cli import app

    monkeypatch.setenv("PBITES_DB_PATH", str(tmp_path / "t.duckdb"))
    runner = CliRunner()
    (tmp_path / "empty").mkdir()
    assert runner.invoke(app, ["ingest-local", str(tmp_path / "empty")]).exit_code == 1
    make_folder(tmp_path / "media")
    result = runner.invoke(app, ["ingest-local", str(tmp_path / "media"), "--tier", "A"])
    assert result.exit_code == 0 and "youtube:abc123" in result.output


def test_non_ascii_text_roundtrips(con, tmp_path):
    """Regression: default Windows encoding (cp1252) cannot represent e.g. U+016B."""
    d = make_folder(tmp_path)
    (d / "source.en.vtt").write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nAloha, Ūlupalakua\n", encoding="utf-8"
    )
    info = json.loads((d / "source.info.json").read_text(encoding="utf-8"))
    info["title"] = "Ūlupalakua session"
    (d / "source.info.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    ingest_folder(con, d)
    assert con.execute("SELECT title FROM source_item").fetchone() == ("Ūlupalakua session",)
    assert con.execute("SELECT text FROM source_caption").fetchone() == ("Aloha, Ūlupalakua",)
