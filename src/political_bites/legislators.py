"""Load politicians and their terms from unitedstates/congress-legislators.

Members of Congress are keyed by Bioguide ID. People who never served in Congress
(e.g. presidents, from ``executive.yaml``) are keyed ``wd:<Wikidata QID>``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import duckdb
import httpx
import yaml

BASE_URL = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/{name}.yaml"
DATASETS = ("legislators-current", "legislators-historical", "executive")

_ROLE = {
    "rep": ("Representative", "house"),
    "sen": ("Senator", "senate"),
    "prez": ("President", "executive"),
    "viceprez": ("Vice President", "executive"),
}


def person_key(person: dict[str, Any]) -> str | None:
    """Stable key: Bioguide ID if present, else ``wd:<QID>``."""
    ids = person.get("id", {})
    if ids.get("bioguide"):
        return ids["bioguide"]
    if ids.get("wikidata"):
        return f"wd:{ids['wikidata']}"
    return None


def parse_people(yaml_text: str) -> dict[str, dict[str, Any]]:
    """Parse a congress-legislators YAML file into ``{politician_id: person}``."""
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    people = yaml.load(yaml_text, Loader=loader) or []
    out: dict[str, dict[str, Any]] = {}
    for person in people:
        key = person_key(person)
        if key:
            out[key] = person
    return out


def fetch_dataset(name: str, cache_dir: Path, *, refresh: bool = False) -> str:
    """Return the YAML text for a dataset, using a local cache."""
    cache = cache_dir / f"{name}.yaml"
    if cache.exists() and not refresh:
        try:
            return cache.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            pass  # stale cache written by an older version in the system encoding; re-download
    resp = httpx.get(BASE_URL.format(name=name), timeout=120, follow_redirects=True)
    resp.raise_for_status()
    cache_dir.mkdir(parents=True, exist_ok=True)
    text = resp.content.decode("utf-8")
    cache.write_text(text, encoding="utf-8")
    return text


def _name(person: dict[str, Any]) -> str:
    n = person.get("name", {})
    return n.get("official_full") or " ".join(x for x in (n.get("first"), n.get("last")) if x)


def upsert_people(
    con: duckdb.DuckDBPyConnection,
    index: dict[str, dict[str, Any]],
    wanted: Iterable[str],
) -> list[str]:
    """Upsert the wanted people (and their terms). Returns the IDs that were not found."""
    missing: list[str] = []
    for pid in wanted:
        person = index.get(pid)
        if person is None:
            missing.append(pid)
            continue
        terms = person.get("terms", [])
        last = terms[-1] if terms else {}
        _, chamber = _ROLE.get(last.get("type"), (None, None))
        external = {k: v for k, v in person.get("id", {}).items() if k != "bioguide"}
        con.execute("DELETE FROM politician_term WHERE politician_id = ?", [pid])
        con.execute("DELETE FROM politician WHERE politician_id = ?", [pid])
        con.execute(
            "INSERT INTO politician (politician_id, name, party, state, chamber, external_ids) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                pid,
                _name(person),
                last.get("party"),
                last.get("state"),
                chamber,
                json.dumps(external, default=str),
            ],
        )
        for t in terms:
            role, term_chamber = _ROLE.get(t.get("type"), (t.get("type"), None))
            con.execute(
                "INSERT INTO politician_term "
                "(politician_id, role, chamber, party, start_date, end_date) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [pid, role, term_chamber, t.get("party"), t.get("start"), t.get("end")],
            )
    return missing
