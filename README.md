# political-bites

A private, human-in-the-loop library of US politician audio clips (2016-present) for
parody/commentary music. See [PLAN.md](PLAN.md) for scope, legal tiers, and phases.

## Quick start

```bash
uv sync
cp .env.example .env
uv run pbites init-db
uv run pbites smoke-run
uv run pytest
```

## Principles

- Audio only; watchlist-driven (`config/watchlist.yaml`, Bioguide IDs).
- Nothing is released without human approval; Tier C audio never leaves the private DB
  (enforced and tested in `political_bites.licensing.can_release_audio`).
- CPU-first; ASR/diarization/isolation backends are swappable.
