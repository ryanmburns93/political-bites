"""Ingest locally acquired media (audio + optional captions + yt-dlp style info.json).

Acquisition happens outside this repo. A media folder looks like::

    data/media/20260721_<videoid>/
        source.flac | source.wav | source.m4a ...   # audio (required)
        source.en.vtt                                 # captions (optional)
        source.info.json                              # yt-dlp metadata (optional)
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from political_bites.licensing import LicenseTier
from political_bites.provenance import record_run

AUDIO_EXTS = (".wav", ".flac", ".m4a", ".mp3", ".opus", ".ogg", ".webm", ".aac")


class IngestError(Exception):
    """Raised when a media folder cannot be ingested."""


@dataclass(frozen=True)
class Cue:
    start_s: float
    end_s: float
    text: str


# ---------------------------------------------------------------- captions

_TIMING = re.compile(
    r"(?P<a>(?:\d+:)?\d{2}:\d{2}\.\d{3})\s*-->\s*(?P<b>(?:\d+:)?\d{2}:\d{2}\.\d{3})"
)
_TAGS = re.compile(r"<[^>]+>")


def _seconds(ts: str) -> float:
    parts = ts.split(":")
    h, m, s = ([0] * (3 - len(parts))) + [float(x) for x in parts]
    return h * 3600 + m * 60 + s


def parse_vtt(text: str) -> list[Cue]:
    """Parse WebVTT into cues, removing YouTube's rolling-caption duplication.

    Auto-generated captions repeat the previous line inside each new cue. A line
    already shown in the previous cue is dropped; cues left empty are skipped.
    """
    cues: list[Cue] = []
    prev_lines: set[str] = set()
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        timing_idx = next((i for i, ln in enumerate(lines) if _TIMING.search(ln)), None)
        if timing_idx is None:
            continue  # header, NOTE, STYLE blocks
        m = _TIMING.search(lines[timing_idx])
        assert m is not None
        raw = [
            re.sub(r"\s+", " ", html.unescape(_TAGS.sub("", ln))).strip()
            for ln in lines[timing_idx + 1 :]
        ]
        raw = [ln for ln in raw if ln]
        fresh = [ln for ln in raw if ln not in prev_lines]
        prev_lines = set(raw)
        if not fresh:
            continue
        cues.append(Cue(_seconds(m["a"]), _seconds(m["b"]), " ".join(fresh)))
    return cues


def detect_caption_type(info: dict[str, Any], lang: str = "en") -> str | None:
    """'uploaded' if the video has uploaded subtitles, 'auto' if only auto-generated."""
    if info.get("subtitles", {}).get(lang):
        return "uploaded"
    if info.get("automatic_captions", {}).get(lang):
        return "auto"
    return None


# ------------------------------------------------------------------- media


def find_audio(folder: Path) -> Path:
    candidates = sorted(p for p in folder.iterdir() if p.suffix.lower() in AUDIO_EXTS)
    preferred = [p for p in candidates if p.stem == "source"]
    chosen = preferred or candidates
    if not chosen:
        raise IngestError(f"No audio file ({', '.join(AUDIO_EXTS)}) in {folder}")
    if len(chosen) > 1:
        names = ", ".join(p.name for p in chosen)
        raise IngestError(f"Multiple audio files in {folder}: {names}; keep one")
    return chosen[0]


def find_media_folders(path: Path) -> list[Path]:
    """A media folder itself, or every immediate subfolder of ``path`` that has audio."""
    if _has_audio(path):
        return [path]
    return sorted(d for d in path.iterdir() if d.is_dir() and _has_audio(d))


def _has_audio(folder: Path) -> bool:
    return any(p.suffix.lower() in AUDIO_EXTS for p in folder.iterdir() if p.is_file())


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def probe_duration(path: Path) -> float | None:
    """Duration in seconds via ffprobe, or None if unavailable."""
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        ).stdout.strip()
        return float(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _load_info(folder: Path) -> dict[str, Any]:
    paths = sorted(folder.glob("*.info.json"))
    if not paths:
        return {}
    try:
        return json.loads(paths[0].read_text())
    except json.JSONDecodeError as exc:
        raise IngestError(f"Invalid JSON in {paths[0]}: {exc}") from exc


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise IngestError(f"Unrecognized date {value!r} (use YYYY-MM-DD)")


def _find_captions(folder: Path, lang: str = "en") -> Path | None:
    for pattern in (f"*.{lang}*.vtt", "*.vtt"):
        found = sorted(folder.glob(pattern))
        if found:
            return found[0]
    return None


# ------------------------------------------------------------------ ingest


def ingest_folder(
    con: duckdb.DuckDBPyConnection,
    folder: Path,
    *,
    tier: LicenseTier | None = None,
    event_type: str | None = None,
    event_date: str | None = None,
) -> str:
    """Ingest one media folder into ``source_item`` / ``source_caption``; returns source_id.

    Re-ingesting the same folder replaces its rows but keeps previously set tier,
    event type and event date unless new values are given. A first ingest with no tier
    defaults to the strictest tier (C); set it explicitly for sources you have verified.
    """
    folder = folder.resolve()
    audio = find_audio(folder)
    info = _load_info(folder)
    file_hash = sha256_file(audio)

    if info.get("id"):
        source_id = f"{(info.get('extractor_key') or 'media').lower()}:{info['id']}"
    else:
        source_id = f"local:{file_hash[:12]}"

    prior = con.execute(
        "SELECT license_tier, event_type, event_at FROM source_item WHERE source_id = ?",
        [source_id],
    ).fetchone()
    tier = tier or (LicenseTier(prior[0]) if prior else LicenseTier.C)
    event_type = event_type or (prior[1] if prior else None)

    event_at = _parse_date(event_date) or (prior[2] if prior else None)
    if event_at is None and info.get("release_timestamp"):
        event_at = datetime.fromtimestamp(info["release_timestamp"], UTC).replace(tzinfo=None)

    cues: list[Cue] = []
    caption_file = _find_captions(folder)
    if caption_file:
        cues = parse_vtt(caption_file.read_text(errors="replace"))
    caption_type = detect_caption_type(info) if cues else None
    if cues and caption_type is None:
        caption_type = "unknown"

    duration = probe_duration(audio) or info.get("duration")

    with record_run(
        con,
        "ingest-local",
        source_id=source_id,
        tool="political-bites",
        params={"folder": str(folder), "tier": str(tier), "cues": len(cues)},
    ):
        con.execute("DELETE FROM source_caption WHERE source_id = ?", [source_id])
        con.execute("DELETE FROM source_item WHERE source_id = ?", [source_id])
        con.execute(
            "INSERT INTO source_item (source_id, platform, organization, url, title, "
            "published_at, event_at, event_type, license_tier, retrieved_at, file_hash, "
            "media_path, duration_s, caption_type, channel_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                source_id,
                (info.get("extractor_key") or "local").lower(),
                info.get("channel") or info.get("uploader"),
                info.get("webpage_url"),
                info.get("title") or folder.name,
                _parse_date(info.get("upload_date")),
                event_at,
                event_type,
                str(tier),
                datetime.now(UTC).replace(tzinfo=None),
                file_hash,
                str(audio),
                duration,
                caption_type,
                info.get("channel_id"),
            ],
        )
        if cues:
            con.executemany(
                "INSERT INTO source_caption VALUES (?, ?, ?, ?, ?)",
                [(source_id, i, c.start_s, c.end_s, c.text) for i, c in enumerate(cues)],
            )
    return source_id
