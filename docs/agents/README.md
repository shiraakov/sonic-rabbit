# Agent skill specs

One file per agent in the ADK content-generation pipeline. Each spec is the source of truth
for that agent's role, I/O contract, tools, instruction prompt, anti-hallucination guardrails,
and trajectory eval shape. The ADK code in `src/music_journey/pipeline/` implements these.

| Agent | File | Type | Purpose |
|---|---|---|---|
| Orchestrator | [orchestrator.md](orchestrator.md) | Workflow (code, no LLM) | Drives one full journey run end-to-end |
| JourneyResearcher | [journey_researcher.md](journey_researcher.md) | LlmAgent | Theme → title, blurb, songs + per-song blurbs |
| SongFetcher | [song_fetcher.md](song_fetcher.md) | LlmAgent + MCP | Per song: preview URL, image, streaming links |
| FactChecker | [fact_checker.md](fact_checker.md) | LlmAgent + MCP | Verify month_year and place via MusicBrainz |
| NarrationGenerator | [narration_generator.md](narration_generator.md) | Code (no LLM) | Gemini TTS → .wav files for intro, blurbs, outro |
| GraphLinker | [graph_linker.md](graph_linker.md) | LlmAgent (light) | Validate + write Journey to data/journeys.json; quality report to data/review/ |

**Pipeline flow:**

```
orchestrator
  → journey_researcher       (theme → draft journey)
      → [per song] song_fetcher    (fill preview_url, image_url)
      → [per song] fact_checker    (verify month_year, place + blurb claims)
  → narration_generator      (TTS all text → .wav files)
  → graph_linker             (validate + publish to data/journeys.json)
```

**Review model (non-blocking):** pipeline publishes directly to `data/journeys.json`.
A quality report is written to `data/review/{journey_id}.json` — unverified claims,
missing previews, TTS failures. Human reads it offline at their own pace and edits
the live file manually if anything needs fixing. No approval gate; no staging step.

**Model:** `LiteLlm(model=os.environ["MODEL_ID"])`, default `gemini/gemini-2.5-flash`.
Key: `GEMINI_API_KEY`. NarrationGenerator uses `gemini-2.5-flash-preview-tts` via REST,
same key.

**Anti-hallucination approach:**
- Every LlmAgent uses a Pydantic output schema (`pipeline/schemas.py`). Structured output
  only — no free-text parsing.
- Field provenance rules enforced in code, not left to the LLM:
  - `preview_url` — SongFetcher MCP tool result only; never accepted from LLM text
  - `place` (where recorded) — FactChecker MusicBrainz lookup only
  - `*_audio_url` — NarrationGenerator only; never LLM-generated strings
- Each agent has a trajectory `.evalset` test in `tests/evals/` covering expected
  tool-call sequence and output schema. No agent is wired into the orchestrator until
  it passes its eval independently.
