"""Word-level transcription of ingested sources (CPU-first, swappable backend).

The heavy dependency (faster-whisper) is optional: ``uv sync --group asr``.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import duckdb

from political_bites.provenance import record_run


class TranscribeError(Exception):
    """Raised when a source cannot be transcribed."""


@dataclass(frozen=True)
class Word:
    start_s: float  # relative to the start of the audio handed to the backend
    end_s: float
    text: str
    probability: float | None = None
    segment_idx: int = 0


class Transcriber(Protocol):
    model_name: str

    def transcribe(self, wav_path: Path) -> Sequence[Word]: ...


class FasterWhisperTranscriber:
    """faster-whisper on CPU. Defaults favor speed: int8, greedy decoding, VAD filter."""

    def __init__(
        self,
        model_size: str = "small.en",
        *,
        compute_type: str = "int8",
        cpu_threads: int = 0,
        beam_size: int = 1,
        vad_filter: bool = True,
        language: str | None = "en",
    ) -> None:
        self.model_name = f"faster-whisper:{model_size}:{compute_type}"
        self._model_size = model_size
        self._compute_type = compute_type
        self._cpu_threads = cpu_threads
        self._beam_size = beam_size
        self._vad_filter = vad_filter
        self._language = language
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise TranscribeError(
                    "faster-whisper is not installed. Run: uv sync --group asr"
                ) from exc
            self._model = WhisperModel(
                self._model_size,
                device="cpu",
                compute_type=self._compute_type,
                cpu_threads=self._cpu_threads,
            )
        return self._model

    def transcribe(self, wav_path: Path) -> list[Word]:
        model = self._load()
        segments, _info = model.transcribe(
            str(wav_path),
            language=self._language,
            beam_size=self._beam_size,
            word_timestamps=True,
            vad_filter=self._vad_filter,
        )
        words: list[Word] = []
        for i, seg in enumerate(segments):  # lazy generator: decoding happens here
            for w in seg.words or []:
                text = w.word.strip()
                if text:
                    words.append(Word(w.start, w.end, text, w.probability, i))
        return words


def default_threads() -> int:
    """Roughly the physical core count (logical count // 2), at least 1."""
    return max(1, (os.cpu_count() or 2) // 2)


def extract_audio_range(src: Path, start_s: float, duration_s: float, out_wav: Path) -> None:
    """Cut [start, start+duration) to 16 kHz mono WAV with ffmpeg."""
    cmd = [
        "ffmpeg", "-nostdin", "-loglevel", "error", "-y",
        "-ss", f"{start_s:.3f}", "-t", f"{duration_s:.3f}",
        "-i", str(src), "-ac", "1", "-ar", "16000", str(out_wav),
    ]  # fmt: skip
    try:
        proc = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", errors="replace", check=False
        )
    except FileNotFoundError as exc:
        raise TranscribeError("ffmpeg not found on PATH; install it to extract audio") from exc
    if proc.returncode != 0 or not out_wav.exists():
        raise TranscribeError(f"ffmpeg failed: {proc.stderr.strip() or proc.returncode}")


@dataclass(frozen=True)
class TranscribeResult:
    source_id: str
    start_s: float
    end_s: float
    n_words: int
    wall_s: float

    @property
    def audio_s(self) -> float:
        return self.end_s - self.start_s

    @property
    def speed(self) -> float:
        """Audio seconds transcribed per wall-clock second (>1 is faster than real time)."""
        return self.audio_s / self.wall_s if self.wall_s > 0 else float("inf")


def transcribe_source(
    con: duckdb.DuckDBPyConnection,
    source_id: str,
    transcriber: Transcriber,
    *,
    start_s: float = 0.0,
    end_s: float | None = None,
    chunk_s: float = 600.0,
    progress: Callable[[TranscribeResult], None] | None = None,
) -> TranscribeResult:
    """Transcribe [start_s, end_s) of a source in chunks and store word timings.

    Each chunk is committed on its own, so an interrupted run keeps finished chunks and
    can be resumed with a later ``start_s``. Words previously stored for the same source
    inside a chunk are replaced, so re-running a range is safe. Stored times are relative
    to the full recording. Words that straddle a chunk boundary may be cut; clip-level
    transcription of exact ranges is done later at higher quality.

    ``progress`` is called after each chunk with that chunk's result.
    """
    row = con.execute(
        "SELECT media_path, duration_s FROM source_item WHERE source_id = ?", [source_id]
    ).fetchone()
    if row is None:
        raise TranscribeError(f"Unknown source_id {source_id!r}; run ingest-local first")
    media_path, duration_s = row
    if not media_path or not Path(media_path).exists():
        raise TranscribeError(f"Audio file for {source_id} not found: {media_path}")
    if start_s < 0:
        raise TranscribeError("start must be >= 0")
    if chunk_s <= 0:
        raise TranscribeError("chunk size must be > 0")
    end = min(end_s, duration_s) if (end_s is not None and duration_s) else (end_s or duration_s)
    if end is None:
        raise TranscribeError("Source has no known duration; pass an explicit end")
    if end <= start_s:
        raise TranscribeError(f"Empty range: start={start_s:.1f}s end={end:.1f}s")

    total_words = 0
    total_wall = 0.0
    with record_run(
        con,
        "transcribe",
        source_id=source_id,
        tool=transcriber.model_name,
        params={"start_s": start_s, "end_s": end, "chunk_s": chunk_s},
    ):
        cursor = start_s
        while cursor < end:
            chunk_end = min(cursor + chunk_s, end)
            t0 = time.perf_counter()
            with tempfile.TemporaryDirectory() as tmp:
                wav = Path(tmp) / "range.wav"
                extract_audio_range(Path(media_path), cursor, chunk_end - cursor, wav)
                words = list(transcriber.transcribe(wav))
            wall = time.perf_counter() - t0
            _store_words(con, source_id, transcriber.model_name, words, cursor, chunk_end)
            total_words += len(words)
            total_wall += wall
            if progress:
                progress(TranscribeResult(source_id, cursor, chunk_end, len(words), wall))
            cursor = chunk_end
    return TranscribeResult(source_id, start_s, end, total_words, total_wall)


def _store_words(
    con: duckdb.DuckDBPyConnection,
    source_id: str,
    model_name: str,
    words: Sequence[Word],
    offset_s: float,
    chunk_end_s: float,
) -> None:
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(
            "DELETE FROM source_word WHERE source_id = ? AND start_s >= ? AND start_s < ?",
            [source_id, offset_s, chunk_end_s],
        )
        if words:
            con.executemany(
                "INSERT INTO source_word VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        source_id,
                        w.segment_idx,
                        w.start_s + offset_s,
                        w.end_s + offset_s,
                        w.text,
                        w.probability,
                        model_name,
                    )
                    for w in words
                ],
            )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
