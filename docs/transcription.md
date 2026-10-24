# Transcription (CPU)

Word-level timings come from [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
running on CPU. It is an optional dependency group so the base install and CI stay light.

```bash
uv sync --group asr
```

Requirements: `ffmpeg` on your PATH (it cuts the audio range before transcription).

## Benchmark first

Find your `source_id` in the output of `ingest-local` (or `SELECT source_id FROM source_item`),
then transcribe a short slice:

```bash
uv run --group asr pbites transcribe <source_id> --minutes 5
```

It prints the speed (`2.0x real time` means 2 minutes of audio per minute of compute) and an
estimate for the whole recording. Compare models on the same slice:

```bash
uv run --group asr pbites transcribe <source_id> --start-min 60 --minutes 5 --model medium.en
```

- First use of a model downloads it from Hugging Face (`small.en` is a few hundred MB,
  `medium.en` over 1 GB). Windows may warn about symlinks; it is harmless.
- `--threads 0` uses about half your logical cores; try matching your physical core count.
- The default is greedy decoding (beam size 1), int8, with a voice-activity filter that skips
  silence. These favor speed; accuracy is refined later on the exact clip ranges.

## Long recordings

Work is committed every `--chunk-min` minutes (default 10). If a run is interrupted, finished
chunks are kept: resume with `--start-min`. Re-running a range replaces its words, never
duplicates them. Words that straddle a chunk boundary can be cut; that does not matter for
locating who is speaking, and clip-level transcription is redone at higher quality later.

Words are stored in `source_word` (times relative to the full recording).
