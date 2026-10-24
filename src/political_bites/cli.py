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
