# Acquiring media (outside this repo)

political-bites does **not** download media. You obtain audio yourself, from sources and
under terms you are comfortable with, and place it under `data/media/` (git-ignored).
Make sure your use of any source complies with its terms of service and the license tiers
in [PLAN.md](../PLAN.md).

## Folder layout

One folder per recording:

```
data/media/20260721_<videoid>/
  source.flac | source.wav | source.m4a ...   # audio (required, exactly one)
  source.en.vtt                                 # captions (optional)
  source.info.json                              # yt-dlp style metadata (optional)
```

`info.json` supplies the title, channel, URL, upload date and duration; without it the
source gets a hash-based ID (`local:<sha256 prefix>`) and fewer metadata fields.

## Example: yt-dlp (your own process)

```bash
yt-dlp -f bestaudio -x --audio-format flac \
  --write-subs --write-auto-subs --sub-langs en --sub-format vtt \
  --write-info-json \
  -o "data/media/%(upload_date)s_%(id)s/source.%(ext)s" "<video URL>"
```

## Ingest

```bash
uv run pbites ingest-local data/media/20260721_<videoid> \
  --tier A --event-type floor --event-date 2026-07-21
uv run pbites ingest-local data/media            # every subfolder that contains audio
```

- `--tier` defaults to **C** (strictest) on first ingest. Set it only for sources you have
  verified (A = House/Senate floor proceedings).
- Re-ingesting is safe: rows are replaced, but tier, event type and event date are kept
  unless you pass new values.
- `--event-date` is the date of the event itself. If omitted, the video's scheduled start
  time is used when the metadata has one; the upload date is stored separately as
  `published_at`.

## Captions

Captions are stored per cue in `source_caption` with their type: `uploaded`, `auto`, or
`unknown`. Treat them as a hint for wording and speaker cues, not as ground truth: live
captions often lag the audio by several seconds, so timestamps come from the audio
alignment in later stages.
