# Demo Script — Sonic Rabbit

**Target length:** under 5 minutes  
**App URL:** http://127.0.0.1:8000  

---

## Setup checklist

- [ ] Server running, homepage loads
- [ ] "It Started With a Choir" journey has full audio (7 songs, previews + narration)
- [ ] Sound working at a comfortable level
- [ ] Browser zoom 100%, window ~1100px wide
- [ ] Terminal window ready with `src/music_journey/mcp_music/server.py` open

---

## Part 1 — Problem (~30 seconds)

> "In today's attention economy, the most-played songs get pushed higher by the algorithm — and that buries the older music that explains where the songs people love actually came from. Young people don't know what influenced the music they listen to, because the algorithm never shows them."

> "Sonic Rabbit fixes that. It's a library of narrated music history journeys — each one a sequence of songs on a shared theme, introduced by a voice that gives you the history and context before the song plays. Not a Wikipedia article. A podcast you actually listen to."

---

## Part 2 — Why agents (~20 seconds)

> "The library needs to grow beyond what any one person can curate. When a user requests a topic the library doesn't have, a multi-agent pipeline builds it autonomously — picking songs, fetching real streaming previews, writing and fact-checking narration, generating audio, and deciding whether to publish. That workflow takes a human hours. The agents do it from a two-sentence request."

---

## Part 3 — Architecture (~20 seconds)

**Show:** the architecture diagram from the README or a slide.

> "The pipeline is six agents in sequence. The web runtime is a separate FastAPI app that reads the pre-generated content — it needs no AI key at serve time. The only shared artifact is a JSON file."

> "Three Google ADK concepts are at work here: a multi-agent pipeline using LlmAgent, an MCP server that gives agents access to iTunes, MusicBrainz, and Wikipedia, and custom agent skills — the three tools the agents call autonomously to fetch previews and verify facts."

---

## Part 4 — Demo (~2 minutes 30 seconds)

### Homepage (20 seconds)

**Show:** homepage grid.

> "Six journeys are live. You can browse by category, use the search box, or hit a prompt chip."

Click **"Take me to church"**.

---

### Journey experience (50 seconds)

**Show:** "It Started With a Choir" journey page loads.

> "The chip routes straight to the gospel journey — how Black church music became the DNA of soul and funk."

Click **"▶ Start listening"**.

> "Intro narration plays — Kokoro-82M, a local ONNX model, no API calls."

Let 8–10 seconds of intro audio play.

> "Song 1 unlocks. The narration names the artist, the year, the recording location — then the 30-second iTunes preview plays."

Let narration play briefly, then skip to preview. Let 5 seconds of preview play.

Click **"Next →"** to unlock song 2. Show the pattern once more, briefly.

---

### Connected journey (20 seconds)

Step or skip to the end of the journey so the conclusion section appears. Show the "Where to next" grid.

> "At the end, the app suggests connected journeys — not random, based on shared categories. Gospel shares 'identity' and 'society and culture' with the Women's journey and the Great Migration. Both appear here."

Click through to one of them briefly.

---

### Search miss + request (40 seconds)

Navigate back to homepage. Type **"songs sent to space"** in the search box.

> "Something the library doesn't have."

**Show:** miss banner.

> "Honest miss — semantic search found nothing above its confidence threshold. It shows the closest result and offers to build what you asked for."

Click **"Request it ↗"**. Fill in title and description quickly.

> "The request goes through rate limiting, a semantic duplicate check, and a Gemini classifier before queuing. If it passes the quality gate after the pipeline runs, it goes live."

Click **"Request →"**. Show the confirmation.

---

## Part 5 — The build (30 seconds)

**Show:** `src/music_journey/mcp_music/server.py` open in editor.

> "The agent skills are custom MCP tools built in this file. `search_track` hits iTunes first, falls back to Deezer, and returns the preview URL and album art. `verify_recording` hits MusicBrainz for recording date and place. `search_wikipedia` handles biographical claims."

> "These are the skills the agents call autonomously — SongFetcher uses search_track to screen candidates, FactChecker uses verify_recording and search_wikipedia to annotate confidence on every blurb claim."

> "Preview URLs are never LLM-generated. They can only come from a tool result — or the song is cut."

---

## Part 6 — Wrap (~10 seconds)

> "Six agents, one MCP server with custom skills, local TTS, and a quality gate — all triggered by a user typing two sentences. Thanks."

---

## Timing guide

| Part | Description | Target |
|------|-------------|--------|
| 1 | Problem | 30s |
| 2 | Why agents | 20s |
| 3 | Architecture | 20s |
| 4a | Homepage | 20s |
| 4b | Journey experience | 50s |
| 4c | Connected journey | 20s |
| 4d | Search miss + request | 40s |
| 5 | The build (MCP skills) | 30s |
| 6 | Wrap | 10s |
| **Total** | | **~4:20** |

---

## Recording notes

- **Opening:** record Parts 1–3 as a voiceover over the architecture diagram or a static title card — no need to have the app on screen yet.
- **Audio during demo:** app audio (narration + preview) plays through speakers. Keep mic away or mute app during Parts 5–6.
- **Connected journey beat:** if the auto-selected journey has no audio, just say "this journey would have narration once the pipeline runs for it" — don't pretend.
- **MCP skills beat:** show the actual file. The three tool functions are the evidence — no need to run anything live here.
- **Pacing:** slightly slower than conversational. You can edit out pauses; you can't fix rushed sections.
