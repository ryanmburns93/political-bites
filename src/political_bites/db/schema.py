"""DuckDB schema (see PLAN.md section 4). Idempotent: safe to run repeatedly."""

from __future__ import annotations

from pathlib import Path

import duckdb

DDL = [
    """
    CREATE TABLE IF NOT EXISTS politician (
        politician_id VARCHAR PRIMARY KEY,
        name VARCHAR NOT NULL,
        party VARCHAR,
        state VARCHAR,
        chamber VARCHAR,
        url VARCHAR,
        external_ids VARCHAR,
        notes VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS politician_term (
        politician_id VARCHAR NOT NULL,
        role VARCHAR,
        chamber VARCHAR,
        party VARCHAR,
        start_date DATE,
        end_date DATE,
        committees VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_item (
        source_id VARCHAR PRIMARY KEY,
        platform VARCHAR NOT NULL,
        organization VARCHAR,
        url VARCHAR,
        title VARCHAR,
        published_at TIMESTAMP,
        event_at TIMESTAMP,
        event_type VARCHAR,
        license_tier VARCHAR NOT NULL,
        retrieved_at TIMESTAMP,
        file_hash VARCHAR,
        audio_fingerprint VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_caption (
        source_id VARCHAR NOT NULL,
        idx INTEGER NOT NULL,
        start_s DOUBLE NOT NULL,
        end_s DOUBLE NOT NULL,
        text VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_speaker (
        source_id VARCHAR NOT NULL,
        diarization_label VARCHAR NOT NULL,
        politician_id VARCHAR,
        role VARCHAR,
        name VARCHAR,
        outlet VARCHAR,
        id_confidence DOUBLE,
        id_method VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS clip (
        clip_id VARCHAR PRIMARY KEY,
        source_id VARCHAR NOT NULL,
        politician_id VARCHAR,
        start_s DOUBLE NOT NULL,
        end_s DOUBLE NOT NULL,
        transcript VARCHAR,
        transcript_confidence DOUBLE,
        context_before VARCHAR,
        context_after VARCHAR,
        license_tier VARCHAR NOT NULL,
        review_status VARCHAR NOT NULL DEFAULT 'pending',
        release_mode VARCHAR NOT NULL DEFAULT 'private',
        raw_path VARCHAR,
        isolated_path VARCHAR,
        commentary_note VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS clip_audio_features (
        clip_id VARCHAR PRIMARY KEY,
        duration_s DOUBLE,
        lufs DOUBLE,
        true_peak_db DOUBLE,
        words_per_sec DOUBLE,
        pause_ratio DOUBLE,
        median_f0_hz DOUBLE,
        snr_db DOUBLE,
        overlap_flag BOOLEAN,
        quality_score DOUBLE,
        hook_score DOUBLE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS clip_topic (
        clip_id VARCHAR NOT NULL,
        topic VARCHAR NOT NULL,
        confidence DOUBLE,
        method VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pipeline_run (
        run_id VARCHAR PRIMARY KEY,
        stage VARCHAR NOT NULL,
        source_id VARCHAR,
        tool VARCHAR,
        tool_version VARCHAR,
        params VARCHAR,
        started_at TIMESTAMP NOT NULL,
        finished_at TIMESTAMP,
        status VARCHAR NOT NULL,
        error VARCHAR
    )
    """,
]


# Columns added after the first release; applied to pre-existing databases.
MIGRATIONS = [
    "ALTER TABLE source_item ADD COLUMN IF NOT EXISTS media_path VARCHAR",
    "ALTER TABLE source_item ADD COLUMN IF NOT EXISTS duration_s DOUBLE",
    "ALTER TABLE source_item ADD COLUMN IF NOT EXISTS caption_type VARCHAR",
    "ALTER TABLE source_item ADD COLUMN IF NOT EXISTS channel_id VARCHAR",
]


def connect(db_path: Path | str) -> duckdb.DuckDBPyConnection:
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path))


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    for stmt in DDL:
        con.execute(stmt)
    for stmt in MIGRATIONS:
        con.execute(stmt)
