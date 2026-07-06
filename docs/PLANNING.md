# Music Journey — Technical Planning Doc (MVP)

> Status: Current. This is the **HOW**. All decisions from SPEC.md §15 are locked
> and reflected here. The WHAT lives in SPEC.md.

---

## 1. Stack decisions

| Layer | Decision | Why |
|---|---|---|
| Language | **Python 3.11+** | One language across core, API, and pipeline. |
| Core / API | **FastAPI** | Async, auto OpenAPI docs (honors "API-first/headless"), minimal boilerplate. |
| Storage | **Flat JSON** (`journeys.json`), loaded into memory, behind a repository interface | No DB, no migrations, human-readable. Ample for ~10 journeys at MVP. Repository interface makes the swap to SQLite a cheap, contained change later. |
| Frontend | **Jinja2 templates + HTMX**, served by FastAPI | Keeps it Python-centric; HTMX handles step-unlock swaps without JS state. |
| Discovery (Rung 2) | **`sentence-transformers` MiniLM** (384-dim, CPU) | Local, no API key, no per-query cost, cannot hallucinate — retrieves existing journeys only. Loaded once at startup. |
| Agent pipeline | **Google ADK**, models via **LiteLLM → Gemini** (`MODEL_ID`, default `gemini/gemini-2.5-flash`) | ADK orchestrates; Gemini is the plugged-in model (key `GEMINI_API_KEY` from `~/.bashrc`). Model is swappable. |
| TTS narration | **Gemini TTS** (`gemini-2.5-flash-preview-tts`), same `GEMINI_API_KEY` | Pre-generated at pipeline time; served as static `.mp3` files. Web runtime needs no TTS key. |
| External sources | **MCP server**: music lookups (iTunes primary, Deezer fallback) + verification (Wikipedia/Wikidata, MusicBrainz) | Snippets + fact-checking for recording date/place. All free, no auth. |
| Deploy / ops | **Google Agents CLI** (`agents-cli`) for scaffold/run/deploy of the agent system | Yields the project link; matches ADK. |

**Headless boundary:** the service layer has zero presentation or framework dependencies.
The JSON API and the HTML/HTMX pages are thin layers over it. The ADK pipeline writes
through the same repository the service reads from.

## 2. Repository structure

```
music_journey_capstone/
├── CLAUDE.md
├── docs/
│   ├── SPEC.md
│   ├── PLANNING.md
│   └── agents/                # per-agent skill specs
├── pyproject.toml
├── .env.example               # GEMINI_API_KEY, MODEL_ID, DATA_DIR
├── src/music_journey/
│   ├── core/                  # headless — NO web/agent deps
│   │   ├── models.py          # Journey, Song (Pydantic)
│   │   ├── repository.py      # abstract Repository interface
│   │   ├── repository_json.py # flat-JSON store (journeys.json)
│   │   ├── services.py        # get_journey, list_journeys, search, semantic_match
│   │   └── config.py          # pydantic-settings (GEMINI_API_KEY, MODEL_ID, DATA_DIR)
│   ├── api/
│   │   ├── main.py            # create_app(), mounts routers + static
│   │   ├── deps.py            # get_services() FastAPI dependency
│   │   ├── routes_json.py     # /api/* JSON endpoints
│   │   └── routes_html.py     # HTML pages (Jinja + HTMX)
│   ├── web/
│   │   ├── templates/
│   │   │   ├── base.html
│   │   │   ├── home.html      # journey grid + chips + search
│   │   │   ├── journey.html   # journey header + song steps
│   │   │   └── _song_step.html # HTMX partial: one unlocked song step
│   │   └── static/
│   │       ├── style.css
│   │       └── placeholder.svg
│   ├── discovery/             # Rung-2 semantic matchmaking
│   │   └── embedder.py        # load MiniLM, embed journeys at startup, cosine match
│   ├── pipeline/              # ADK content generation (not part of web runtime)
│   │   ├── agents.py          # orchestrator + subagents
│   │   ├── schemas.py         # Pydantic extraction schemas
│   │   ├── tts.py             # Gemini TTS calls → data/audio/{journey_id}/*.mp3
│   │   └── run.py             # entrypoint: theme string → writes via repository
│   └── mcp_music/             # MCP server (external sources)
│       └── server.py
├── data/
│   ├── journeys.json          # content store
│   ├── audio/                 # TTS narration files, served at /audio/
│   │   └── {journey_id}/
│   │       ├── intro.mp3
│   │       ├── outro.mp3
│   │       └── song_01.mp3 … song_N.mp3
│   └── staging/               # pipeline output before human review
└── tests/
    ├── test_repository_json.py
    ├── test_services.py
    ├── test_api_json.py
    ├── test_discovery.py      # embedding + cosine match
    └── evals/                 # ADK .evalset trajectory tests, one per subagent
```

## 3. Data model (flat JSON)

One file: `data/journeys.json` — a JSON array of Journey records.

### Journey record

```json
{
  "id": "journey:great-migration",
  "title": "From the Delta to Detroit",
  "subtitle": "How the Great Migration transformed American music",
  "theme": "geopolitical movement",
  "blurb": "...",
  "intro_audio_url": "/audio/journey:great-migration/intro.mp3",
  "outro_audio_url": "/audio/journey:great-migration/outro.mp3",
  "image_url": "https://...",
  "prompt_chips": ["Take me somewhere political"],
  "songs": [
    {
      "position": 1,
      "title": "Cross Road Blues",
      "artist": "Robert Johnson",
      "month_year": "November 1936",
      "place": "San Antonio, Texas",
      "blurb": "...",
      "blurb_audio_url": "/audio/journey:great-migration/song_01.mp3",
      "preview_url": "https://...",
      "image_url": "https://...",
      "streaming_links": {
        "spotify": "https://...",
        "apple_music": "https://...",
        "youtube": "https://..."
      }
    }
  ]
}
```

**Field notes:**
- `month_year` — string, not a date type; use `"November 1936"` or `"1936"` when month unknown
- `place` — where recorded (not artist origin, not lyrical setting); sourced from MusicBrainz
- `preview_url` — from iTunes/Deezer MCP tool only; never LLM-generated
- `prompt_chips` — list of homepage chip labels that route to this journey (Rung 1 discovery)
- `intro_audio_url` / `outro_audio_url` / `blurb_audio_url` — TTS `.mp3` files generated by
  the pipeline, stored in `data/audio/{journey_id}/`, served at `/audio/...`. `null` if TTS
  generation failed — UI degrades to text-only gracefully.

**In-memory indexes (built on load):**
- `id → Journey`
- `theme → [Journey]`
- `embedding → np.array` (one vector per journey, built by `embedder.py` at startup)

## 4. Service layer

Pure functions over the repository — no FastAPI or ADK imports:

- `get_journey(id) -> Journey`
- `list_journeys(theme=None) -> list[Journey]`
- `get_journey_step(journey_id, position) -> Song` — returns the song at a given step
- `semantic_match(text, threshold=0.35) -> MatchResult` — cosine match over journey embeddings;
  returns `{journey, score}` or `{miss: True, closest: Journey}` below threshold
- `resolve_chip(label) -> Journey | None` — maps a chip label to its journey
- `get_playlist(journey_id) -> list[Song]` — all songs in order
- Write side (pipeline only): `upsert_journey(journey)`, `delete_journey(id)`

## 5. HTTP API (JSON)

All entity IDs contain colons — use `{id}` not `{id:path}`.

```
GET  /api/journeys                     → list[JourneySummary]
GET  /api/journeys/{id}                → Journey (full, all songs)
GET  /api/journeys/{id}/songs/{pos}    → Song (one step)
GET  /api/journeys/{id}/playlist       → list[Song] (ordered)
GET  /api/search?q=                    → {journey, score} | {miss, closest}
GET  /api/chips                        → list[{label, journey_id}]
GET  /health                           → {status, journeys: N}
```

## 6. Frontend pages

### 6.1 Homepage (`/`)

- Journey **card grid**: thumbnail, title, theme tag.
- **Starter chip row** (Rung 1) — hand-configured chips below the search box, e.g.
  *"Take me somewhere political"*, *"One object, many decades"*, *"Surprise me"* (random).
  Each chip calls `GET /api/chips` and routes to the matched journey.
- **Free-text search box** — on submit, calls `GET /api/search?q=`; hit → redirect to
  `/j/{id}`; miss → render miss state inline with closest journey surfaced.
- **"I'm feeling lucky"** button → random journey.

### 6.2 Journey page (`/j/{id}`)

- **Header:** title, subtitle, theme tag, journey-level blurb (text always visible).
- **Intro narration:** `<audio autoplay>` of `intro_audio_url` on page load. Gracefully
  absent if `intro_audio_url` is null (text is still there).
- **Song list:** all songs rendered in order. Only song at `current_step` is fully expanded.
  Songs ahead are collapsed placeholders.
- **Step progression:** HTMX-swaps the next `_song_step.html` partial. Server-rendered.
- **Progress indicator:** "Song 3 of 8."
- **End state:** closing narration audio + downloadable playlist + "try another journey" card.

### 6.3 Song step partial (`_song_step.html`)

Rendered by `GET /j/{id}/step/{pos}` (HTMX target). The **podcast unit**:
1. `<audio autoplay>` of `blurb_audio_url` (narration). Skip button available.
2. Full blurb text (always visible, regardless of audio state).
3. `<audio>` of `preview_url` (30s snippet) — auto-plays after narration ends via JS
   `onended` event on the narration player. Skip button available.
4. Song metadata: title, artist, `month_year`, `place`.
5. Album art (`referrerpolicy="no-referrer"`).
6. "Next →" button (if not last); "Finish journey" (if last).

### 6.4 Playlist download

`GET /j/{id}/playlist.txt` — plain-text file, one line per song (`Title — Artist`), with
streaming deep links below each entry. An `.m3u` variant at `/j/{id}/playlist.m3u`.

### 6.5 Session state

Session-only breadcrumb via query param `?from={journey_id}`. No server-side session store.

## 7. Discovery layer (`src/music_journey/discovery/`)

**Embedder** (`embedder.py`):
1. On startup, load `sentence-transformers` MiniLM once (CPU, ~90MB, ~1s cold load).
2. For each journey, concatenate `title + " " + theme + " " + blurb[:500]` and embed.
3. Store all vectors in a `np.ndarray` alongside a `[journey_id]` index list.

**Query path** (triggered by search box):
1. Embed user query text (~10ms).
2. Cosine similarity against all journey vectors.
3. If best score ≥ threshold (default 0.35): return that journey.
4. If best score < threshold: return miss + closest journey.

**Rung 1 chip config** (`discovery/chips.py` or `data/chips.json`): a static list of
`{label, journey_id}` pairs — hand-maintained, loaded at startup. No AI involved.

**Miss state (Rung 3):** miss shows closest journey + a one-click **"want this? +1"** that
appends the query to `data/demand_log.jsonl` for future roadmap seeding. No generative AI
in MVP; the "miss sketch" Gemini call is deferred post-MVP.

## 8. Content pipeline (ADK multi-agent)

**Entrypoint:** `pipeline/run.py --theme "songs about shoes"` → generates and persists one
journey. Runs once per seed theme. Output is a `Journey` record written via `upsert_journey`.

**Human-in-the-loop:** the pipeline writes to a staging file (`data/staging/`). A human
reviews and approves before the journey is promoted to `data/journeys.json`. Approval is a
CLI command: `pipeline/approve.py --id journey:shoes`.

### Agent topology

```
Orchestrator (code)
  └─ JourneyResearcher (LlmAgent)
  │    theme string → draft Journey (title, subtitle, blurb, closing_paragraph, songs + blurbs)
  │    └─ [per song] SongFetcher (LlmAgent + MCP)
  │         → preview_url, image_url, streaming_links
  │    └─ [per song] FactChecker (LlmAgent + MCP)
  │         → corrects month_year, place; marks verified
  └─ NarrationGenerator (code, not LlmAgent)
  │    Calls Gemini TTS API directly (not via ADK LlmAgent — deterministic, no reasoning needed)
  │    → intro.mp3, outro.mp3, song_01.mp3 … song_N.mp3 → data/audio/{journey_id}/
  │    Populates intro_audio_url, outro_audio_url, blurb_audio_url on Journey/Song objects
  └─ GraphLinker (code-heavy LlmAgent)
       writes validated Journey (text + audio URLs) to data/staging/{journey_id}.json
```

Agent specs live in `docs/agents/`.

### JourneyResearcher

- **Input:** theme string (e.g. `"songs about shoes"`), min/max song count (6/10).
- **Output (Pydantic schema):**
  - Journey `title`, `subtitle`, `blurb`
  - List of songs: `title`, `artist`, `month_year` (best-effort), `place` (best-effort), `blurb`
- **Constraint:** `month_year` and `place` are flagged as *unverified* in the schema — the
  FactChecker is the authority. The researcher provides a starting point, not final values.
- **No hallucination of preview URLs** — `preview_url` is left empty; SongFetcher fills it.

### SongFetcher

- Calls MCP `search_track(title, artist)` → `preview_url`, `image_url`, `album`, streaming links.
- If iTunes returns no result: tries Deezer fallback.
- If both miss: marks song `preview_url: null` (unplayable at MVP; not a blocker).

### FactChecker

- Calls MCP `verify_recording(title, artist)` → cross-references MusicBrainz + Wikipedia.
- **Corrects `month_year` and `place`** to sourced values when the researcher's best-effort
  was wrong. Both fields must be MusicBrainz-grounded or flagged as unverified.
- Marks each song `verified: true/false`.

### NarrationGenerator

Implemented in `pipeline/tts.py` — pure Python, not an ADK LlmAgent (TTS is deterministic;
no reasoning required).

- Calls `gemini-2.5-flash-preview-tts` via the Gemini REST API with the same `GEMINI_API_KEY`.
- Generates one `.mp3` per text segment: journey intro, closing paragraph, and each song blurb.
- Files written to `data/audio/{journey_id}/intro.mp3`, `outro.mp3`, `song_01.mp3` … `song_N.mp3`.
- Updates the Journey/Song objects in memory with the corresponding URL paths before GraphLinker
  persists them.
- **On failure:** logs the error, sets the field to `null`, and continues — TTS failure does not
  abort the pipeline. Missing audio → text-only UI gracefully.
- **Voice consistency:** uses a fixed voice name per run so all clips in a journey sound like
  the same narrator.

### GraphLinker

- Validates the full Journey schema (text + audio URL fields).
- Writes to `data/staging/{journey_id}.json` via `upsert_journey`.
- Logs a summary: N songs found, N verified, N missing previews, N missing audio clips.

### Anti-hallucination

- **Structured output:** every LlmAgent uses a Pydantic schema (`pipeline/schemas.py`).
- **Trajectory `.evalset` tests** (`tests/evals/`): one per subagent, asserting expected
  tool-call path + output-schema groundedness. Run via `google-agents-cli` eval tooling.
  No agent is wired into the orchestrator until it passes its eval independently.
- **Field provenance rules:** `preview_url` from MCP only; `place`/`month_year` MusicBrainz-grounded;
  `*_audio_url` from NarrationGenerator only — never LLM-generated strings.
- **Human review gate** before any journey reaches the live store.

**Model:** `LiteLlm(model=os.environ["MODEL_ID"])`, default `gemini/gemini-2.5-flash`.

## 9. MCP server

`mcp_music/server.py` — Python MCP server (stdio transport).

**Music-lookup tools** (SongFetcher):
- `search_track(title, artist) -> {preview_url, image_url, album, year, source}`
  Backends: iTunes Search API (no auth) primary, Deezer fallback.

**Verification tools** (FactChecker):
- `verify_recording(title, artist) -> {recording_date, recording_place, sources: [...]}`
  Backends: MusicBrainz (recording metadata) + Wikipedia (cross-reference).
  Returns source list so the agent can report provenance.

All free, no auth. HTTP responses cached in memory during a pipeline run.

## 10. Build sequence

> Each milestone is independently demoable. Tests are written before implementation.
> No milestone advances until its definition of done is met.

### M0 — Scaffold
Repo layout, `pyproject.toml`, `src/` package structure, FastAPI hello-world, empty
`data/journeys.json` loads cleanly, `.env.example`.
*Done: app boots; `GET /health` returns `{status: ok, journeys: 0}`.*

### M1 — Core + POC seed
Implement `Journey`/`Song` models, `repository_json`, service layer. Hand-seed both POC
journeys (Great Migration + shoes) directly into `data/journeys.json`.
*Done: `list_journeys()` returns both; `get_journey()` returns full song list for each.*

### M2 — POC UI (discovery + reading + podcast experience)
JSON API routes + HTML pages:
- Homepage: journey grid, Rung-1 chips, "I'm feeling lucky."
- Journey page: intro narration audio + blurb text, step-by-step song unlock (HTMX swap),
  per-step narration → preview sequence, progress indicator, end-of-journey closing narration.
- Playlist download (plain-text).
- Mount `data/audio/` as FastAPI static files at `/audio/`.
- Hand-generate TTS audio for at least one song step in each POC journey (one-off Gemini TTS
  call) so the podcast UX is demonstrable without the full pipeline.
*Done: a user can land on the homepage, click "Take me somewhere political," hear the intro
narration, step through the Great Migration journey hearing narration → preview for each song,
and download the playlist at the end. Same path works for the shoes journey.*

### M3 — Semantic search (Rung 2 + Rung 3)
Add `discovery/embedder.py`: embed the two POC journeys at startup; wire search box to cosine
match; implement miss state with closest-journey + "+1" demand logger.
*Done: typing "tell me about Black music moving north" returns the Great Migration journey;
"footwear through the decades" returns the shoes journey; "songs about dinosaurs" shows the miss
state with the demand log entry written.*

### M4 — Content pipeline (agents, one at a time)
Build MCP server, then each agent independently with its trajectory eval before integration:
  1. `SongFetcher` — validate iTunes/Deezer calls + MCP tool roundtrip.
  2. `FactChecker` — validate MusicBrainz/Wikipedia verification.
  3. `JourneyResearcher` — validate structured output schema.
  4. `NarrationGenerator` (`pipeline/tts.py`) — validate Gemini TTS calls, file output,
     and URL population on Journey/Song objects. Test graceful null on API failure.
  5. `GraphLinker` — validate staging write + schema (including audio URL fields).
  6. Wire `Orchestrator` — run `pipeline/run.py --theme "songs about shoes"` end-to-end.
  7. Human review via `approve.py` → promote to live store; confirm UI plays narration.

*Done: every agent passes its eval; the pipeline generates a fully narrated journey that a
human can review and approve. The "you give a theme, AI builds, you approve" loop works,
including audio.*

### M5 — Seed the 10 journeys
**This is the theme-input + review loop in practice.** You hand-pick ~8 additional themes
(beyond the 2 POC journeys), run `pipeline/run.py --theme "..."` for each, review the staging
output, and approve or reject. Rejected runs are flagged for pipeline tuning.
*Done: homepage grid shows ~10 journeys; all passed human review; semantic search
meaningfully differentiates them.*

### M6 — Visual polish
Album art, journey thumbnails, song-step layout, end-of-journey screen. Dark music theme.
*Done: looks demo-ready on desktop and mobile.*

### M7 — Deliverables
Deploy via `agents-cli` (project link), record public video (demo + pipeline walk-through),
assemble media gallery, write Kaggle writeup.
*Done: all four SPEC.md §14 submission outputs complete.*

## 11. Testing strategy

- **Unit:** `test_repository_json.py` — empty store, missing file, load + index, upsert.
- **Unit:** `test_services.py` — all service functions against the two POC journeys as fixture.
- **Contract:** `test_api_json.py` — all JSON API routes with dependency overrides.
- **Discovery:** `test_discovery.py` — embedding produces expected match for known queries;
  miss state triggers correctly below threshold.
- **Smoke:** `test_smoke.py` — `/health` against real data; homepage loads without errors.
- **Pipeline:** schema-validation tests + stubbed MCP so pipeline tests don't hit live sources.
- **Trajectory evals:** `tests/evals/*.evalset` — one per subagent; assert tool-call path +
  output groundedness. Gate: no agent is wired until its eval passes.

## 12. Config & secrets

`.env` (never committed):
```
GEMINI_API_KEY=   # sourced from ~/.bashrc
MODEL_ID=gemini/gemini-2.5-flash
DATA_DIR=data
```

`.env.example` documents all three. External sources (iTunes, Deezer, Wikipedia, MusicBrainz)
require no keys.

The web runtime needs no `GEMINI_API_KEY` at serve time (no live generation in MVP).
The pipeline needs it; the web app does not.

## 13. Risks & mitigations

- **Snippet gaps** — iTunes/Deezer misses a song → SongFetcher marks `preview_url: null`;
  UI shows "no preview available." Mainstream catalog keeps this rare.
- **Unverifiable recording metadata** — MusicBrainz doesn't have every session; FactChecker
  marks `verified: false` rather than guessing. Human reviewer decides whether to accept.
- **Embedding cold-load latency** — MiniLM loads in ~1s on startup. Acceptable; not per-request.
- **Scope creep** — milestones stop at M7; geo/accounts/streaming integration stay out.
- **Pipeline content drift** — human review gate before any journey goes live.
