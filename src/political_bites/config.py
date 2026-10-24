from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, overridable via env vars prefixed PBITES_ or a .env file."""

    model_config = SettingsConfigDict(env_prefix="PBITES_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    db_path: Path = Path("data/pbites.duckdb")
    watchlist_path: Path = Path("config/watchlist.yaml")
    congress_api_key: str | None = None
    hf_token: str | None = None  # only needed for gated pyannote models

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"


class WatchlistEntry(BaseModel):
    politician_id: str
    note: str = ""


def load_watchlist(path: Path) -> list[WatchlistEntry]:
    """Load the user-specified politician watchlist (Bioguide IDs)."""
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [WatchlistEntry(**row) for row in raw.get("politicians", [])]
