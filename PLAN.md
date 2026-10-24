# Political Audio Clip Library: Project Plan

Status: DRAFT for approval. Date: 2026-10-24.
Goal: an organized, queryable library of speech snippets from US politicians, cut into clean, production-ready clips with rich metadata, usable for EDM sampling and optionally hosted publicly.

---

## 0. Decisions needed before building

1. **Source scope for v1.** Recommended: public-domain government video only (House/Senate floor, official federal channels). Everything else is "metadata-only" until licensing is clear (see section 1).
2. **Public hosting scope.** Recommended: host audio only for Tier A (public domain) clips; for other tiers host only a metadata index with timestamped links back to the source.
   - **Decided: fully unmonetized.** No ads, royalties, tips, or paid tiers on the site or on uploaded tracks. Purpose is parody/commentary and public dialogue. Costs are covered out of pocket (or donations only after legal review).
   - Release modes tracked per clip: `private`, `public_unmonetized` (v1 target), `monetized` (out of scope; revisit only with legal review).
3. **Compute.** Whisper large-class ASR and Demucs want a GPU. Options: local GPU, rented cloud GPU by the hour, or CPU-only with smaller models (slower, lower accuracy).
4. **"Position" definition.** Recommended: role at time of clip (Senator, Representative, Speaker, committee chair, President, etc.) plus optional per-clip stance label, kept separate and clearly marked as model-generated.
5. **Stack preference.** Python + SQL, `uv`-managed (per your standing preference). Starting storage: DuckDB/Parquet + local files, migrating to Postgres + object storage when hosting begins.

---

## 0.5 Locked scope (as of 2026-10-24)

- **Audio only.** No video storage; fetch video only transiently if a source forces it, then keep the audio track.
- **Date range:** 2016 to present.
- **Politicians:** user-specified watchlist (`config/watchlist.yaml` of Bioguide IDs), not open-ended harvesting. Discovery only looks for these people.
- **Human-in-the-loop is the core workflow:** automation proposes (candidate segments, speaker, transcript, topic); the human approves. Nothing is `approved` without a human action.
- **Database stays private.** Only finished, production-ready tracks (and Tier A clips if desired) are ever released. Release is an explicit export step gated on `review_status=approved` + `license_tier` + `release_mode`.
- **Compute: CPU-first, no GPU assumed.**
  - Target only the watchlist speakers' time ranges (floor markers / Congressional Record tell us when they spoke) instead of transcribing whole days of audio.
  - ASR with faster-whisper int8 on CPU (small/medium English models); use the Congressional Record or captions as a cross-check/prior where available.
  - Run Demucs/denoise only on clips that pass a first-pass quality gate, not on every segment.
  - Heavy one-off backfills can burst to rented hourly GPU or a managed ASR API; the pipeline treats the ASR/diarization/isolation backends as swappable so a local GPU later is a config change, not a rewrite.

---

## 1. Legal and ethical guardrails (build into the schema from day one)

Not legal advice; get a short consult with an IP/media lawyer before any public hosting or commercial music release.

**Source tiers (stored per clip as `license_tier`):**

| Tier | Material | Reuse posture |
|---|---|---|
| A | House and Senate floor proceedings (government-owned cameras) | Public domain. C-SPAN has said floor footage is public domain; strip any C-SPAN branding/graphics if you take it from their feed. Safe to host. |
| A- | Other official federal sources (White House, agencies, member/committee official channels) | Generally US government works, but verify per source; some content includes third-party material (music, stock footage, outside speakers). |
| B | C-SPAN-produced footage (committee hearings, press events, Washington Journal) | C-SPAN has a published policy allowing non-commercial copying/posting with attribution for federal-government events. That policy dates from 2007: re-read the current policy before relying on it. Non-commercial only, so conflicts with commercial music release. |
| C | Network news, cable, YouTube uploads by media orgs, social media | Copyrighted. Private research/transformation only. Do not host audio publicly. Store metadata, URL, and timestamps only. |

**Unmonetized parody/commentary posture (v1):**
- Unmonetized use strengthens the fair-use position and removes demonetization/revenue-redirect risk, but does not make Tier C material safe: automated claims, mutes, blocks, and strikes can still hit uploads.
- Fair use favors commentary directed at the speaker or their statements over using a clip only as a rhythmic hook. Record a short `commentary_note` per released track (what the piece is saying) and keep surrounding context linkable.
- Hosting Tier C audio on our own domain is distribution of a copyrighted work; keep Tier C as metadata + timestamped links only.
- Tracks that sample Tier C clips go to platforms at the uploader's risk; prefer Tier A samples for anything meant to stay up reliably.

**Separate from copyright (applies even to Tier A):**
- Right of publicity / false-endorsement risk: a politician's voice in a commercially released track can imply endorsement. Keep edits non-deceptive; no synthetic/cloned voices; no splicing words to change meaning. Consider a "context preserved" flag and always link to the full source.
- Election-period sensitivity: avoid releasing clips of current candidates in ways that could read as campaign material. Add a disclaimer page.
- Takedown process and contact on the hosted site; provenance retained per clip so removal is easy.
- Respect platform terms of service when downloading (YouTube etc.). Prefer official APIs/bulk downloads from government sources over scraping.
- Non-politician voices (interviewers, citizens, witnesses) appear in clips: default to excluding them from hosted clips or tagging them separately.

---

## 2. Source plan (ranked)

### Primary (start here): public domain, structured, scrapable
1. **House floor video, HouseLive (live.house.gov), archive 2009 to present.** The Clerk publishes per-day MP4 and MP3 downloads and a video search API (Granicus-based) that queries markers across the library. Floor summaries available as XML per legislative day. Best first source: clean audio, known speakers, public domain.
2. **Senate floor video (senate.gov floor activity archive).** Same legal posture; less structured, so expect more scraping and manual mapping.
3. **Congress.gov API (api.congress.gov/v3).** Free key. Use for members, committees, hearings metadata, bills, Congressional Record: the join layer for speaker, party, committee, and bill linkage. Committee-meeting video metadata is still evolving there; Senate committee videos have been embedded on Congress.gov since 2024 (recent years only).
4. **Congressional Record (govinfo.gov).** Text of floor speeches: useful to validate/correct ASR transcripts and to resolve who spoke.
5. **`unitedstates/congress-legislators` (GitHub, open data).** Bioguide IDs, party, chamber, state, terms, social handles. Use Bioguide ID as the canonical politician key.

### Secondary: richer content, more licensing care
6. **C-SPAN (c-span.org video library).** Largest searchable archive of speeches, hearings, and events with transcripts and speaker tagging. Tier B terms.
7. **Official committee YouTube channels and member channels.** Easy to find hearings and statements; verify each channel's status. House committees embed YouTube on Congress.gov.
8. **White House video (whitehouse.gov and official channels).** Presidential addresses, briefings, remarks. Verify embedded third-party material.
9. **Federal agencies / independent commissions** (FCC, FTC, SEC, Fed press conferences) for officials and agency heads, if scope includes them.

### Discovery only (Tier C: use for finding moments, not hosting)
10. **Internet Archive TV News Archive.** Caption-searchable archive of US TV news (over a million shows since 2009), with curated Congress and Executive Branch clip collections. Use captions to find when a politician said something; check Internet Archive terms before any reuse.
11. **YouTube search/API** (official channels of networks, debate hosts, campaigns), **Commission on Presidential Debates**, network sites (PBS NewsHour, NPR transcripts, etc.).
12. **Your own feeds:** capture the URLs you naturally see and add them to a manual "seed queue" (CSV or a browser bookmarklet). Good for taste, not scalable.

**Source adapter interface:** every source implements `discover() -> [SourceItem]` and `fetch(item) -> media + raw_metadata`, so new sources are plug-ins.

---

## 3. Pipeline architecture

```
discover -> fetch -> normalize -> ASR+align -> diarize -> speaker ID
   -> segment -> isolate/enhance -> analyze -> classify -> QA/review -> publish
```

Every stage is idempotent, keyed on `source_id` + stage version, and writes artifacts + a row of provenance (tool, model, version, params, time).

| Stage | Detail | Candidate tools |
|---|---|---|
| Discover | Poll sources/schedules, dedupe by URL and by audio fingerprint | httpx, yt-dlp (Tier C, personal use), chromaprint |
| Fetch | Download best audio (and video if wanted), hash, store original untouched | ffmpeg |
| Normalize | 48 kHz WAV working copy (plus 16 kHz for models), loudness measured not yet changed | ffmpeg, pyloudnorm |
| ASR + word alignment | Word-level timestamps, confidence | WhisperX (faster-whisper + wav2vec2 alignment). Alternative: managed ASR with built-in diarization |
| Diarization | Turn boundaries with anonymous speaker labels; flag overlapped speech | pyannote (community-1 / 3.1, needs Hugging Face token) or NeMo-based pipeline (no token, heavier) |
| Speaker ID | Map anonymous speakers to Bioguide IDs (see below) | speaker embeddings (pyannote/ECAPA) + official metadata |
| Segmentation | Cut into clips on phrase/sentence boundaries | custom, using word timings and pauses |
| Voice isolation | Separate speech from room noise, music, applause, crosstalk | Demucs (vocals stem), DeepFilterNet / similar denoiser; keep both raw and isolated versions |
| Audio analysis | See section 5 | librosa, parselmouth/CREPE, pyloudnorm |
| Classification | Topic, stance, tone tags | LLM with fixed taxonomy + structured output, validated against Congressional Record/bill data |
| QA / review | Confidence gates + small human review UI | Streamlit or simple web app |
| Publish | Export to storage, search index, public site | Parquet, Postgres/pgvector, object storage |

**Speaker identification strategy (the hard part), in order of reliability:**
1. Official metadata: floor markers/agenda and Congressional Record tell you who is recognized to speak at what time.
2. Caption/transcript speaker cues ("Mr. SMITH of Ohio...") and presiding-officer introductions ("The gentleman from Ohio is recognized").
3. Voice enrollment: build a reference embedding per politician from verified clean clips; match diarized speakers by cosine similarity with a threshold.
4. Optional face/chyron match for video sources.
Anything below confidence threshold goes to the review queue; never auto-publish an uncertain attribution (mis-attributed quotes are the worst failure mode here).

---

## 4. Data model (Postgres/DuckDB)

- `politician`: politician_id (PK), name, party (current), state, chamber, photo/URL, notes
- `politician_term`: politician_id, role, chamber, party, start/end dates, committee roles (so party/position is correct *at clip date*, including party switches)
- `source_item`: source_id, platform, organization/outlet, url, title, original_publish_datetime, event_datetime, event_type (floor, hearing, interview, speech, debate, ad), license_tier, retrieved_at, file_hash, audio_fingerprint
- `source_speaker`: source_id, diarization label, person (politician_id or null), role (politician/interviewer/witness/other), name, outlet, id_confidence, id_method
- `clip`: clip_id, source_id, speaker (politician_id), start/end seconds, duration, transcript, transcript_confidence, context_before/after, license_tier, review_status, paths to raw/isolated files
- `clip_audio_features`: see section 5
- `clip_topic`: clip_id, topic (controlled vocabulary), confidence, method; plus free-form tags and linked bill IDs where applicable
- `clip_stance` (optional, marked as model-generated): clip_id, subject, label, confidence
- `pipeline_run`: stage, tool/model/version/params, timestamps, status, error

**Topic taxonomy:** start from the Congress.gov / CRS Policy Area list (about 30 areas: Health, Taxation, Environmental Protection, Armed Forces and National Security, Immigration, Economics and Public Finance, etc.) and add a small custom layer (corruption/ethics, elections, media, tone tags like "emphatic", "humorous", "angry"). A fixed vocabulary keeps filtering and hosted browse clean.

---

## 5. Audio characteristics to catalog (for production)

Per clip:
- Duration, start/end offsets, silence padding available before/after (for clean cuts)
- Integrated loudness (LUFS), true peak, clipping flag, dynamic range
- Speech rate: words/sec and syllables/sec from word alignment; pause ratio; longest internal pause
- Pitch: median F0, range (speaker register), plus pitch-contour summary (rising/falling ending, helps melodic placement)
- Estimated key/pitch class of voiced speech (rough, optional) and a "tempo-friendliness" score: how well the speech rhythm fits common EDM tempi (e.g., 120–150 BPM) with stretch ratio needed
- Noise/SNR estimate, reverb estimate, background music/applause/crosstalk flags, overlapped-speech flag
- Spectral summary (centroid, tilt) and a quality score (0–1) combining the above
- "Chop-ability" / hook score: clip is short, self-contained, with strong stress and clean boundaries
- Loop-ready variants: 1–3 s, 3–8 s, 8–15 s cuts at zero crossings with short fades

Store both the **raw cut** (provenance, unaltered) and the **isolated cut** (WAV 48 kHz/24-bit) with identical timing. Normalization to a target loudness is applied only to a separate export, never to the stored master.

---

## 6. Hosting plan (phase 4)

- Static-first public site (search by politician, party, topic, date, source, duration, quality) backed by an API over Postgres.
- Object storage + CDN for audio; downloadable bundles by politician/topic.
- Only Tier A clips (plus Tier B where terms allow, non-commercial, with attribution) get audio hosting.
- Every clip page shows: speaker, role and party at the time, date, source and link to the original full video at the timestamp, transcript, license tier, and a "report/takedown" link.
- Open data export (Parquet/CSV + a dataset card), optionally mirrored to Hugging Face Datasets or Internet Archive.
- Public API with rate limits, plus an attribution/ethics page ("do not use to fabricate quotes or imply endorsement").

---

## 7. Phases and acceptance criteria

**Phase 0: Scaffolding (1–2 days)**
- Repo with `uv` (`pyproject.toml`, `uv.lock`, `src/` layout), ruff, pytest, pre-commit, CI, `.env.example`, config via pydantic-settings.
- Schema migrations, storage abstraction (local first), pipeline run logging.
- *Done when:* `uv sync && uv run pytest` passes in CI and an empty pipeline run records provenance.

**Phase 1: Vertical slice on House floor video (about 1 week)**
- Congress-legislators + Congress.gov ingest for politicians/terms.
- HouseLive adapter: download one legislative day, ASR, diarization, speaker ID using floor metadata, segmentation, isolation, features, topic tags.
- *Done when:* 50 clips from one day, with manual spot check showing at least 95% correct speaker attribution (human-verified), transcripts matched against Congressional Record, features populated.

**Phase 2: Scale and quality (1–2 weeks)**
- Backfill a few months, add Senate floor, voice-enrollment embeddings, review UI, quality scoring, dedupe, batch orchestration (Prefect/Dagster or cron + queue) with retries and cost/time reporting.
- *Done when:* thousands of clips, review queue under control, throughput and per-hour-of-audio cost documented.

**Phase 3: Secondary sources (1–2 weeks)**
- C-SPAN adapter under Tier B rules; official channel/White House adapters; Tier C discovery adapter (metadata only); seed-queue ingestion from your own finds.
- *Done when:* tiers enforced end to end (a Tier C item can never reach a public export).

**Phase 4: Production tooling (about 1 week)**
- Search CLI/notebook helpers, tempo-match filtering, export to sample packs (WAV + JSON/CSV manifest, Ableton/Serato-friendly naming).
- *Done when:* "give me 20 clean 2–6 s healthcare clips from senators, 100–130 words/min" returns a ready folder.

**Phase 5: Public hosting (1–2 weeks, after legal check)**
- API, site, bundles, takedown flow, dataset card.

---

## 8. Proposed repo layout

```
political-bites/
  pyproject.toml  uv.lock  README.md  PLAN.md
  src/political_bites/
    config.py  db/  storage/
    sources/      # house_live.py senate.py congress_gov.py cspan.py youtube.py ...
    stages/       # fetch normalize asr diarize speaker_id segment isolate analyze classify
    review/       # QA app
    export/       # packs, parquet, site data
    cli.py
  tests/  data/fixtures/
  docs/  (sources.md, licensing.md, schema.md)
```

---

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Wrong speaker attribution | Multi-signal ID, confidence thresholds, human review before publish |
| Licensing/takedown | License tier per clip, Tier C never hosted, provenance retained |
| Misleading context | Store surrounding context, link to full source, prohibit deceptive edits in terms |
| Diarization errors on overlap/crosstalk | Overlap flag, exclude from clip candidates, review queue |
| Gated model access / API changes | Pin versions; keep NeMo-based fallback; source adapters isolated |
| GPU cost | Process only speech segments of target speakers; cache; batch |
| Source structure changes (Senate/C-SPAN scraping) | Adapter tests with fixtures, rely on official APIs/bulk data where available |
| Political-neutrality perception | Balanced ingestion rules by party/chamber, documented selection criteria, transparent methodology page |

---

## 10. Open questions for you

1. Is any of this destined for a commercial release (streaming, sales)? That changes which tiers are usable.
2. Which politicians/eras matter most (current Congress only, or historical presidents too)?
3. Do you want video clips too, or audio only?
4. GPU access: local, cloud, or none?
5. Balanced coverage across parties as a design principle, or purely taste-driven?

---

## Sources consulted
- C-SPAN copyright policy discussion (floor footage public domain; non-commercial reuse with attribution for federal events): vondranlegal.com, EFF, TVTechnology
- HouseLive.gov developer resources (MP3/MP4 downloads, video search API): houselive.gov
- Congress.gov API: blogs.loc.gov, congressionaldata.org (Senate committee video embedded as of 2024)
- Internet Archive TV News Archive: blog.archive.org
- WhisperX + pyannote + Demucs pipelines: github.com/m-bain/whisperX, github.com/MahmoudAshraf97/whisper-diarization, pyannote model cards
