from __future__ import annotations

from pathlib import Path

import typer

from political_bites import __version__
from political_bites.config import Settings, load_watchlist
from political_bites.db import connect, init_schema
from political_bites.ingest import IngestError, find_media_folders, ingest_folder
from political_bites.legislators import DATASETS, fetch_dataset, parse_people, upsert_people
from political_bites.licensing import LicenseTier
from political_bites.provenance import record_run
from political_bites.transcribe import (
    FasterWhisperTranscriber,
    TranscribeError,
    TranscribeResult,
    default_threads,
    transcribe_source,
)

app = typer.Typer(help="political-bites: curate politician audio clips.", no_args_is_help=True)


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


@app.command("init-db")
def init_db() -> None:
    """Create the DuckDB database and tables (idempotent)."""
    settings = Settings()
    con = connect(settings.db_path)
    init_schema(con)
    typer.echo(f"Initialized {settings.db_path}")


@app.command("watchlist")
def show_watchlist() -> None:
    """Show the configured politician watchlist."""
    settings = Settings()
    entries = load_watchlist(settings.watchlist_path)
    if not entries:
        typer.echo(f"No politicians in {settings.watchlist_path}")
    for e in entries:
        typer.echo(f"{e.politician_id}\t{e.note}")


@app.command("smoke-run")
def smoke_run() -> None:
    """Record an empty pipeline run to verify provenance logging end to end."""
    settings = Settings()
    con = connect(settings.db_path)
    init_schema(con)
    with record_run(con, "smoke", tool="political-bites", tool_version=__version__) as run_id:
        typer.echo(f"Recorded run {run_id}")


@app.command("load-legislators")
def load_legislators(refresh: bool = typer.Option(False, help="Re-download source data.")) -> None:
    """Load watchlist politicians and their terms from congress-legislators."""
    settings = Settings()
    wanted = [e.politician_id for e in load_watchlist(settings.watchlist_path)]
    if not wanted:
        typer.echo(f"No politicians in {settings.watchlist_path}")
        raise typer.Exit(1)
    con = connect(settings.db_path)
    init_schema(con)
    cache_dir = settings.data_dir / "reference"
    index: dict = {}
    with record_run(
        con, "load-legislators", tool="congress-legislators", params={"n": len(wanted)}
    ):
        for name in DATASETS:
            index.update(parse_people(fetch_dataset(name, cache_dir, refresh=refresh)))
        missing = upsert_people(con, index, wanted)
    typer.echo(f"Loaded {len(wanted) - len(missing)} of {len(wanted)} politicians")
    for pid in missing:
        typer.echo(f"  not found: {pid}", err=True)
    if missing:
        raise typer.Exit(1)


@app.command("ingest-local")
def ingest_local(
    path: Path = typer.Argument(
        ..., exists=True, file_okay=False, help="Media folder, or a folder of them."
    ),
    tier: LicenseTier | None = typer.Option(
        None, help="License tier. First ingest defaults to C (strictest); re-ingest keeps it."
    ),
    event_type: str | None = typer.Option(None, help="e.g. floor, hearing, interview, speech."),
    event_date: str | None = typer.Option(None, help="Date of the event, YYYY-MM-DD."),
) -> None:
    """Ingest locally downloaded audio (+ captions, info.json) into the database."""
    settings = Settings()
    con = connect(settings.db_path)
    init_schema(con)
    folders = find_media_folders(path)
    if not folders:
        typer.echo(f"No media folders with audio found under {path}", err=True)
        raise typer.Exit(1)
    failed = 0
    for folder in folders:
        try:
            source_id = ingest_folder(
                con, folder, tier=tier, event_type=event_type, event_date=event_date
            )
            typer.echo(f"ingested {source_id}  ({folder.name})")
        except IngestError as exc:
            failed += 1
            typer.echo(f"skipped {folder.name}: {exc}", err=True)
    if failed:
        raise typer.Exit(1)


def _hms(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


@app.command("transcribe")
def transcribe_cmd(
    source_id: str = typer.Argument(..., help="source_id printed by ingest-local."),
    start_min: float = typer.Option(0.0, help="Start offset in minutes."),
    minutes: float | None = typer.Option(None, help="Length in minutes (default: to the end)."),
    model: str = typer.Option("small.en", help="faster-whisper model, e.g. small.en, medium.en."),
    threads: int = typer.Option(0, help="CPU threads (0 = about half the logical cores)."),
    compute_type: str = typer.Option("int8", help="CTranslate2 compute type."),
    chunk_min: float = typer.Option(10.0, help="Commit progress every N minutes."),
) -> None:
    """Transcribe a source to word-level timings (CPU). Start with --minutes 5 to benchmark."""
    settings = Settings()
    con = connect(settings.db_path)
    init_schema(con)
    transcriber = FasterWhisperTranscriber(
        model, compute_type=compute_type, cpu_threads=threads or default_threads()
    )
    row = con.execute(
        "SELECT duration_s FROM source_item WHERE source_id = ?", [source_id]
    ).fetchone()
    total_s = row[0] if row else None
    state = {"audio": 0.0, "wall": 0.0}

    def show(chunk: TranscribeResult) -> None:
        state["audio"] += chunk.audio_s
        state["wall"] += chunk.wall_s
        speed = state["audio"] / state["wall"] if state["wall"] else 0.0
        remaining = None
        if total_s and speed:
            remaining = max(0.0, (end_s or total_s) - chunk.end_s) / speed
        eta = f", ~{_hms(remaining)} left" if remaining is not None else ""
        typer.echo(
            f"  {_hms(chunk.start_s)}-{_hms(chunk.end_s)}: {chunk.n_words} words, "
            f"{speed:.2f}x real time{eta}"
        )

    end_s = None if minutes is None else (start_min + minutes) * 60
    try:
        result = transcribe_source(
            con,
            source_id,
            transcriber,
            start_s=start_min * 60,
            end_s=end_s,
            chunk_s=chunk_min * 60,
            progress=show,
        )
    except TranscribeError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        f"{source_id}: {result.n_words} words from {_hms(result.start_s)} to "
        f"{_hms(result.end_s)} in {_hms(result.wall_s)} ({result.speed:.2f}x real time)"
    )
    if total_s and result.speed:
        typer.echo(f"Full recording ({_hms(total_s)}) would take ~{_hms(total_s / result.speed)}.")
