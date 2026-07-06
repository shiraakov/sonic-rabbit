# JourneyResearcher

**Type:** LlmAgent  
**Model:** `gemini/gemini-2.5-flash` via LiteLLM  
**MCP tools:** none (pure generation)

## Role

Takes a theme string and produces a complete draft Journey: title, subtitle, journey-level
blurb, a closing paragraph, and a list of 6–10 songs each with its own blurb. This is the
creative heart of the pipeline. Every other agent enriches or verifies what this one writes.

## Input

```python
class ResearcherInput(BaseModel):
    theme: str          # e.g. "songs about shoes", "the Great Migration"
    min_songs: int = 6
    max_songs: int = 10
```

## Output schema (`pipeline/schemas.py`)

```python
class SongDraft(BaseModel):
    position: int
    title: str
    artist: str
    month_year: str     # best-effort; FactChecker will verify
    place: str          # best-effort; FactChecker will verify
    blurb: str          # must mention artist name, year, and place

class JourneyDraft(BaseModel):
    title: str
    subtitle: str
    theme: str
    blurb: str                  # journey-level intro (1–3 paragraphs)
    closing_paragraph: str      # end-of-journey wrap-up
    songs: list[SongDraft]
```

`preview_url`, `image_url`, `streaming_links`, and all `*_audio_url` fields are
**not in this schema** — the researcher must not generate them. They are filled
by downstream agents only.

## Instruction (system prompt)

```
You are a music historian writing content for a curated listening app.

Given a theme, produce a Journey: a chronological sequence of {min}–{max} real songs
that share the theme. The journey should tell a coherent story — each song should
connect meaningfully to the ones before and after it.

For the journey-level blurb (1–3 paragraphs): explain what connects these songs and
why this sequence matters. Write for a curious non-expert; assume no prior knowledge.

For each song blurb (1–2 paragraphs): explain how this song fits the journey's theme
and how it relates to the previous song. The blurb MUST mention the artist's name,
the year the song was recorded, and the city/place where it was recorded — listeners
hear blurbs as narration and won't see the metadata separately.

For the closing paragraph: tie the arc together. What did the listener just travel through?

Rules:
- Songs must be real, commercially released recordings.
- month_year and place are your best estimate; the FactChecker will verify them.
  Write "unknown" if you genuinely have no idea — do not fabricate.
- Do not include preview_url, image_url, or any streaming links — you do not have
  access to those sources.
- Archetype: decide if this is a causal/historical journey (each song caused the next)
  or an associative/topical journey (songs share an object or concept). Make the blurbs
  reflect whichever it is.
```

## Anti-hallucination guardrails

- Structured output only — `JourneyDraft` schema; no free text accepted.
- `month_year` and `place` explicitly marked as unverified in the schema; FactChecker
  is the authority. Researcher fields are starting points only.
- Trajectory eval (`tests/evals/journey_researcher.evalset`) asserts:
  - Output parses as `JourneyDraft`
  - Song count within min/max bounds
  - No `preview_url` or audio URL fields present in output
  - Each blurb mentions the artist name, a year, and a place
