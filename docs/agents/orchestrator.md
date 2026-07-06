# Orchestrator

**Type:** Workflow agent (deterministic Python code, no LLM)  
**ADK class:** `SequentialAgent` or hand-rolled async loop in `pipeline/run.py`

## Role

Drives a single journey-generation run from a theme string to a staged JSON file.
Calls each subagent in sequence, passes state between them, and handles failures
without aborting the full run (partial output is better than no output).

## Entrypoint

```
uv run python -m music_journey.pipeline.run --theme "songs about shoes"
```

Optional flags:
- `--min-songs N` (default 6)
- `--max-songs N` (default 10)
- `--voice NAME` (default `Kore` — Gemini TTS voice, kept consistent per journey)
- `--dry-run` — generate text only, skip TTS and SongFetcher (fast iteration)

## Control flow

```python
draft    = await journey_researcher.run(theme, min_songs, max_songs)
songs    = await asyncio.gather(
               *[song_fetcher.run(s) for s in draft.songs],
               *[fact_checker.run(s) for s in draft.songs],
           )
journey  = merge(draft, songs)          # merge enriched fields back into draft
journey  = await narration_generator.run(journey, voice=voice)
await graph_linker.run(journey)
```

SongFetcher and FactChecker run concurrently per song (independent).
NarrationGenerator runs after both complete (needs final verified text).

## Failure handling

| Failure | Behaviour |
|---------|-----------|
| SongFetcher returns no preview_url | `preview_url = null`; log; continue |
| FactChecker cannot verify a field | `metadata_verified = false`; log; continue |
| FactChecker finds unverified blurb claims | flagged in review file; continue |
| NarrationGenerator TTS call fails | `*_audio_url = null`; log; continue |
| JourneyResearcher fails | Abort run; raise error |
| GraphLinker fails | Abort run; raise error |

A journey with some null fields or unverified claims is still published. Issues are
captured in the review file for the human to address at their own pace.

## Review model (non-blocking)

The pipeline publishes directly to `data/journeys.json`. There is no approval gate.

A separate review file is written to `data/review/{journey_id}.json` containing the
full quality report from FactChecker and GraphLinker — unverified metadata, unverified
blurb claims, missing previews, TTS failures. The human reads this file offline,
at their own time, and manually edits `data/journeys.json` if anything needs fixing.

## State passed between agents

```python
@dataclass
class PipelineState:
    theme: str
    voice: str
    journey: Journey          # mutated in place as agents enrich it
    run_log: list[str]        # human-readable notes for the reviewer
```
