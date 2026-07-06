# GraphLinker

**Type:** LlmAgent (light — mostly validation, minimal generation)  
**Model:** `gemini/gemini-2.5-flash` via LiteLLM  
**MCP tools:** none

## Role

Final agent in the pipeline. Takes the fully-enriched Journey object (text + audio URLs
+ verified metadata) produced by all upstream agents, validates it against the full
`Journey` schema, writes a human-readable run summary, and persists the result to
`data/journeys.json` (live store) via `repository.upsert_journey()`.

The LLM component is light: it writes the run summary and flags any quality concerns
for the human reviewer. The persistence step is deterministic code.

## Input

The complete `Journey` object after orchestrator has merged all agent outputs.

## Output schema

```python
class LinkerOutput(BaseModel):
    journey_id: str
    songs_total: int
    songs_metadata_verified: int    # FactChecker sourced month_year + place
    songs_missing_preview: int      # preview_url is null
    songs_missing_audio: int        # blurb_audio_url is null
    songs_with_unverified_claims: int  # blurb had claims FactChecker couldn't corroborate
    quality_flags: list[str]        # specific issues: "song 3 place unverified",
                                    # "song 5: claim 'X' not corroborated", etc.
    reviewer_note: str              # 1–3 sentence summary for the human approver
```

After generating this output, the agent (via orchestrator code) calls:
```python
repository.upsert_journey(journey)   # writes to data/staging/
```

## Instruction (system prompt)

```
You are doing a final quality check on a music journey before it goes to human review.

Review the journey for:
- Any songs where metadata_verified=false (recording date/place not sourced)
- Any songs where any_unverified_claims=true (blurb contains claims that couldn't
  be corroborated — list the specific unverified claims in quality_flags)
- Any songs missing preview_url (no audio snippet found)
- Any songs missing blurb_audio_url (TTS generation failed)

Write a brief reviewer_note (1–3 sentences) summarising the journey and flagging
anything the human reviewer should pay attention to before approving. If there are
unverified blurb claims, name them explicitly so the reviewer knows what to check.

Do not rewrite or change any content. Your job is to report, not to fix.
```

## Persistence (code, not LLM)

The orchestrator calls `repository.upsert_journey(journey)` after the LLM output is
received. The journey is written **directly to `data/journeys.json`** (live store) — no
approval gate, no staging step.

Separately, the full quality report is written to `data/review/{journey_id}.json`:

```json
{
  "journey_id": "journey:shoes",
  "generated_at": "2026-07-01T14:23:00Z",
  "songs_metadata_verified": 7,
  "songs_missing_preview": 2,
  "songs_missing_audio": 0,
  "songs_with_unverified_claims": 3,
  "quality_flags": [
    "song 3: place unverified (no MusicBrainz entry)",
    "song 6: claim 'million-dollar Adidas deal' not corroborated"
  ],
  "reviewer_note": "..."
}
```

The human reads `data/review/` at their own pace. If something needs fixing, they edit
`data/journeys.json` directly or delete the journey and re-run the pipeline.

## Trajectory eval

`tests/evals/graph_linker.evalset` asserts:
- Output parses as `LinkerOutput`
- `songs_total` matches the count of songs in the input Journey
- `reviewer_note` is non-empty
- Journey exists in `data/journeys.json` after the run
- Review file exists at `data/review/{journey_id}.json` after the run
