"""Pipeline-run provenance: every stage execution is recorded, success or failure."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import duckdb


@contextmanager
def record_run(
    con: duckdb.DuckDBPyConnection,
    stage: str,
    *,
    source_id: str | None = None,
    tool: str | None = None,
    tool_version: str | None = None,
    params: dict | None = None,
) -> Iterator[str]:
    """Record a stage run in ``pipeline_run``; marks it failed if the body raises."""
    run_id = uuid.uuid4().hex
    con.execute(
        "INSERT INTO pipeline_run VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'running', NULL)",
        [
            run_id,
            stage,
            source_id,
            tool,
            tool_version,
            json.dumps(params or {}),
            datetime.now(UTC).replace(tzinfo=None),
        ],
    )
    try:
        yield run_id
    except Exception as exc:
        con.execute(
            "UPDATE pipeline_run SET status='failed', error=?, finished_at=? WHERE run_id=?",
            [repr(exc), datetime.now(UTC).replace(tzinfo=None), run_id],
        )
        raise
    else:
        con.execute(
            "UPDATE pipeline_run SET status='succeeded', finished_at=? WHERE run_id=?",
            [datetime.now(UTC).replace(tzinfo=None), run_id],
        )
