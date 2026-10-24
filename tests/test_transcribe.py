import importlib.util
import shutil
import wave
from pathlib import Path

import pytest
from typer.testing import CliRunner

from political_bites import transcribe as tr
from political_bites.cli import app
from political_bites.db import connect, init_schema
from political_bites.transcribe import (
    FasterWhisperTranscriber,
    TranscribeError,
    TranscribeResult,
    Word,
    extract_audio_range,
    transcribe_source,
)


def make_wav(path: Path, seconds: float, rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))


class FakeTranscriber:
    """One word per chunk at 1.0-1.5 s (relative), recording how it was called."""

    model_name = "fake:test"

    def __init__(self, fail_on_call: int | None = None):
        self.calls = 0
        self.fail_on_call = fail_on_call

    def transcribe(self, wav_path):
        self.calls += 1
        if self.fail_on_call == self.calls:
            raise RuntimeError("model blew up")
        return [Word(1.0, 1.5, "hello", 0.9, 0), Word(2.0, 2.5, "world", 0.8, 0)]


@pytest.fixture
def extract_calls(monkeypatch):
    calls: list[tuple[float, float]] = []

    def fake_extract(src, start_s, duration_s, out_wav):
        calls.append((start_s, duration_s))
        out_wav.write_bytes(b"")

    monkeypatch.setattr(tr, "extract_audio_range", fake_extract)
    return calls


@pytest.fixture
def con(tmp_path):
    c = connect(":memory:")
    init_schema(c)
    audio = tmp_path / "source.wav"
    make_wav(audio, 1)
    c.execute(
        "INSERT INTO source_item (source_id, platform, license_tier, media_path, duration_s) "
        "VALUES ('s1', 'local', 'A', ?, 25.0)",
        [str(audio)],
    )
    return c


def words(con):
    return con.execute("SELECT start_s, word FROM source_word ORDER BY start_s, word").fetchall()


def test_chunks_offsets_and_progress(con, extract_calls):
    seen = []
    result = transcribe_source(con, "s1", FakeTranscriber(), chunk_s=10, progress=seen.append)
    assert extract_calls == [(0.0, 10.0), (10.0, 10.0), (20.0, 5.0)]
    assert [w for w, _ in words(con)] == [1.0, 2.0, 11.0, 12.0, 21.0, 22.0]
    assert result.n_words == 6 and result.audio_s == 25.0
    assert [(c.start_s, c.end_s) for c in seen] == [(0, 10), (10, 20), (20, 25)]
    assert con.execute("SELECT model FROM source_word LIMIT 1").fetchone() == ("fake:test",)
    assert con.execute("SELECT status FROM pipeline_run").fetchone() == ("succeeded",)


def test_rerun_replaces_only_its_range(con, extract_calls):
    transcribe_source(con, "s1", FakeTranscriber(), chunk_s=10)
    transcribe_source(con, "s1", FakeTranscriber(), start_s=10, end_s=20, chunk_s=10)
    assert len(words(con)) == 6  # replaced the middle chunk, not duplicated
    transcribe_source(con, "s1", FakeTranscriber(), start_s=0, end_s=10, chunk_s=10)
    assert [w for w, _ in words(con)] == [1.0, 2.0, 11.0, 12.0, 21.0, 22.0]


def test_end_is_clamped_to_duration(con, extract_calls):
    result = transcribe_source(con, "s1", FakeTranscriber(), start_s=20, end_s=999, chunk_s=60)
    assert result.end_s == 25.0 and extract_calls == [(20.0, 5.0)]


def test_failure_keeps_finished_chunks_and_marks_run_failed(con, extract_calls):
    with pytest.raises(RuntimeError, match="blew up"):
        transcribe_source(con, "s1", FakeTranscriber(fail_on_call=2), chunk_s=10)
    assert [w for w, _ in words(con)] == [1.0, 2.0]  # chunk 1 survived
    assert con.execute("SELECT status FROM pipeline_run").fetchone() == ("failed",)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"source_id": "nope"}, "Unknown source_id"),
        ({"start_s": -1}, "start must be"),
        ({"chunk_s": 0}, "chunk size"),
        ({"start_s": 30}, "Empty range"),
    ],
)
def test_input_validation(con, extract_calls, kwargs, match):
    args = {"source_id": "s1", **kwargs}
    with pytest.raises(TranscribeError, match=match):
        transcribe_source(con, args.pop("source_id"), FakeTranscriber(), **args)


def test_missing_audio_file(con, extract_calls):
    con.execute("UPDATE source_item SET media_path = 'does-not-exist.wav'")
    with pytest.raises(TranscribeError, match="not found"):
        transcribe_source(con, "s1", FakeTranscriber())


def test_result_speed():
    r = TranscribeResult("s", 0, 600, 10, 100)
    assert r.speed == 6.0 and r.audio_s == 600


@pytest.mark.skipif(
    importlib.util.find_spec("faster_whisper") is not None, reason="faster-whisper installed"
)
def test_missing_faster_whisper_gives_install_hint(tmp_path):
    make_wav(tmp_path / "a.wav", 1)
    with pytest.raises(TranscribeError, match="uv sync --group asr"):
        FasterWhisperTranscriber().transcribe(tmp_path / "a.wav")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_extract_audio_range_with_real_ffmpeg(tmp_path):
    src, out = tmp_path / "src.wav", tmp_path / "out.wav"
    make_wav(src, 3, rate=44100)
    extract_audio_range(src, 1.0, 1.0, out)
    with wave.open(str(out), "rb") as w:
        assert w.getnchannels() == 1 and w.getframerate() == 16000
        assert w.getnframes() == pytest.approx(16000, abs=400)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_extract_audio_range_reports_ffmpeg_errors(tmp_path):
    with pytest.raises(TranscribeError, match="ffmpeg failed"):
        extract_audio_range(tmp_path / "missing.wav", 0, 1, tmp_path / "out.wav")


def test_cli_transcribe(tmp_path, monkeypatch, extract_calls):
    class CliFake(FakeTranscriber):
        def __init__(self, model, *, compute_type, cpu_threads):
            super().__init__()
            assert (model, compute_type) == ("small.en", "int8") and cpu_threads >= 1

    monkeypatch.setattr("political_bites.cli.FasterWhisperTranscriber", CliFake)
    db = tmp_path / "t.duckdb"
    monkeypatch.setenv("PBITES_DB_PATH", str(db))
    audio = tmp_path / "source.wav"
    make_wav(audio, 1)
    seed = connect(db)
    init_schema(seed)
    seed.execute(
        "INSERT INTO source_item (source_id, platform, license_tier, media_path, duration_s) "
        "VALUES ('s1', 'local', 'A', ?, 3600.0)",
        [str(audio)],
    )
    seed.close()

    runner = CliRunner()
    ok = runner.invoke(app, ["transcribe", "s1", "--minutes", "5", "--chunk-min", "2"])
    assert ok.exit_code == 0, ok.output
    assert "words from 0:00:00 to 0:05:00" in ok.output
    assert "Full recording (1:00:00) would take" in ok.output
    assert extract_calls == [(0.0, 120.0), (120.0, 120.0), (240.0, 60.0)]

    bad = runner.invoke(app, ["transcribe", "missing"])
    assert bad.exit_code == 1 and "Unknown source_id" in bad.output
