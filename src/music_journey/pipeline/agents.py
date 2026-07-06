"""ADK LlmAgent definitions for the content-generation pipeline.

Pipeline agents (in execution order):
  1. SongPicker     — theme → CandidateList (titles/artists only, over-generates)
  2. SongFetcher    — (title, artist) → FetcherOutput  [runs on all candidates]
  3. ContentWriter  — confirmed song list → JourneyDraft  [after preview screening]
  4. FactChecker    — (song + blurb) → CheckerOutput  [confirmed songs only]
  5. GraphLinker    — full Journey JSON → LinkerOutput + quality report

MCP server: src/music_journey/mcp_music/server.py (stdio transport).
Model: native Gemini via google.adk.models.Gemini (supports tools + output_schema).
"""

from __future__ import annotations

import sys

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioConnectionParams
from mcp import StdioServerParameters

from .schemas import CandidateList, CheckerOutput, FetcherOutput, JourneyDraft, LinkerOutput

_MODEL_ID = "gemini-2.5-flash"

_PYTHON = sys.executable
_MCP_ARGS = ["-m", "music_journey.mcp_music.server"]


def _mcp_toolset() -> MCPToolset:
    return MCPToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(command=_PYTHON, args=_MCP_ARGS),
        )
    )


def make_song_picker() -> LlmAgent:
    """Pass 1: theme → CandidateList (title + artist only, no blurbs).

    Over-generates by ~4 songs so the fetcher can screen for streaming availability
    and still hit the target count. No MCP tools needed — pure generation.
    """
    return LlmAgent(
        name="song_picker",
        model=Gemini(model=_MODEL_ID),
        output_schema=CandidateList,
        output_key="candidate_list",
        instruction="""
You are curating a playlist of real songs for a music history journey.

Given a theme and a target count, propose (target + 4) candidates in chronological
order. The extras exist because some tracks may not have streaming previews; the
pipeline screens for availability before writing any content.

For each candidate provide:
- title: exact commercial release title
- artist: exact artist name as it appears on the recording
- month_year: your best estimate of the recording date (e.g. "November 1936",
  or just "1958" when the month is unknown)
- place: where the song was physically recorded — not where the artist is from,
  not where the lyrics are set

Prefer well-known recordings with strong mainstream catalog presence: major-label
releases, charting singles, widely-streamed tracks. Obscure B-sides and bootlegs
are unlikely to have a 30-second preview on iTunes or Deezer — avoid them.

Order candidates chronologically. Do NOT write blurbs — those come later, after
streaming availability is confirmed.
""".strip(),
    )


def make_song_fetcher() -> LlmAgent:
    """SongFetcher: (title, artist) → FetcherOutput with preview_url and image_url.

    Runs on ALL candidates before content is written. iTunes first, Deezer fallback.
    """
    return LlmAgent(
        name="song_fetcher",
        model=Gemini(model=_MODEL_ID),
        tools=[_mcp_toolset()],
        output_schema=FetcherOutput,
        output_key="fetcher_result",
        instruction="""
You are fetching music metadata for a song. Use the search_track tool to find
the song, then extract preview_url, image_url, and streaming_links from the result.

Call iTunes first via search_track. If preview_url is missing or null in the
result, call search_track again with source preference noted (the tool handles
Deezer fallback automatically).

If both sources return nothing useful, return null for all fields — that is not
an error; it means the song is not in those catalogs.

Do not invent or guess URLs. Only return URLs that appear in tool results.
""".strip(),
    )


def make_content_writer() -> LlmAgent:
    """Pass 2: confirmed song list → full JourneyDraft with blurbs.

    Runs AFTER the fetcher has confirmed which songs have streaming previews.
    Blurbs are written for the actual final set, so narrative flow is coherent.
    No MCP tools needed — pure generation.
    """
    return LlmAgent(
        name="content_writer",
        model=Gemini(model=_MODEL_ID),
        output_schema=JourneyDraft,
        output_key="journey_draft",
        instruction="""
You are a music historian writing content for a curated listening app.

You will receive a confirmed list of songs (title, artist, month_year, place)
that have been verified to have streaming previews. Write the full journey
content for this exact list — do not add, remove, or reorder songs.

Write:
1. title — punchy, witty, avoids clichés (e.g. "It Started With a Choir" not
   "The Gospel Journey")
2. subtitle — one sharp line expanding the title
3. blurb (journey-level, 1–3 paragraphs) — identify the musical DNA that
   runs through all these songs: a shared rhythmic feel, chord vocabulary,
   structural device, or sonic texture. Write for a curious non-expert who
   will listen with fresh ears — help them know what to listen FOR.
4. For each song, a blurb (1–2 paragraphs): ground the song in its sound first —
   the groove, the hook, the chord changes, the arrangement choice that makes it
   land. Then connect it musically to what came before: a recurring rhythm,
   a lifted chord progression, a call-and-response pattern, a timbral echo.
   MUST mention the artist's name, the year recorded, and the place where it
   was recorded — listeners hear blurbs as narration and will not see metadata.
5. closing_paragraph — describe the musical arc: what sonic elements stayed
   constant, what evolved, what the listener's ear was just trained to notice.

Musical connections to highlight (pick what's genuine for the songs at hand):
- Repeated chord progressions or cadences (e.g. I-IV-V, 12-bar blues, modal)
- Rhythmic figures that recur or mutate across tracks (shuffle, backbeat, syncopation)
- Call-and-response structures (vocal/instrumental, lead/chorus, question/answer)
- Timbral lineage (e.g. acoustic guitar → electric guitar → distorted guitar)
- Melodic hooks that echo earlier songs in the journey
- Structural forms that persist (verse-chorus, 32-bar standard, through-composed)

Keep it accessible — no jargon without brief explanation. Do not fabricate
dates or places — use exactly what is in the confirmed list.
""".strip(),
    )


def make_fact_checker() -> LlmAgent:
    """FactChecker: (title, artist, month_year, place, blurb) → CheckerOutput.

    Two jobs: verify metadata via MusicBrainz, corroborate blurb claims via Wikipedia.
    Runs only on the confirmed final song list (after preview screening).
    """
    return LlmAgent(
        name="fact_checker",
        model=Gemini(model=_MODEL_ID),
        tools=[_mcp_toolset()],
        output_schema=CheckerOutput,
        output_key="checker_result",
        instruction="""
You are fact-checking a song entry for a music history app. You have two jobs.

JOB 1 — Metadata verification:
Use verify_recording to look up the recording date and location in MusicBrainz.
If MusicBrainz has no entry, try search_wikipedia with the song title and artist.
Correct month_year and place if the sourced value differs from what was provided.
"place" means where the song was physically recorded — not where the artist is
from, not where the lyrics are set.

JOB 2 — Blurb claim corroboration:
Read the blurb and identify every specific, verifiable factual claim (dates,
numbers, named events, named people, cause-and-effect assertions). Skip
subjective editorial statements — those are opinion, not fact.

For each claim, call search_wikipedia to find a corroborating source.
Assign confidence: "high" if Wikipedia directly states it, "medium" if
MusicBrainz/Wikidata matches it, "low" if nothing was found.

Do NOT rewrite the blurb. Flag unverified claims; do not fix them.
A low-confidence claim is not necessarily wrong — it may just be obscure.
""".strip(),
    )


def make_graph_linker() -> LlmAgent:
    """GraphLinker: full Journey JSON → LinkerOutput + quality report.

    Light LLM work: validates quality, writes reviewer_note. Persistence is in
    the orchestrator (deterministic code), not here.
    """
    return LlmAgent(
        name="graph_linker",
        model=Gemini(model=_MODEL_ID),
        output_schema=LinkerOutput,
        output_key="linker_result",
        instruction="""
You are the final quality gate for a music journey pipeline. Review the journey
JSON and decide autonomously whether to publish.

COUNT from the journey JSON:
- songs_total: number of songs
- songs_metadata_verified: songs where metadata_verified=true
- songs_missing_preview: songs where preview_url is null or empty
- songs_missing_audio: songs where blurb_audio_url is null or empty
- songs_with_unverified_claims: songs where any_unverified_claims=true

PUBLISH CRITERIA — set publish=true only if ALL hold:
1. songs_total >= 5  (journey is substantial enough)
2. songs_missing_preview == 0  (every song must have a preview; without audio there is no point)
3. songs_missing_audio <= songs_total // 2  (narration must cover at least half)

If any criterion fails, set publish=false and set rejection_reason to a single
clear sentence naming the specific failure (e.g. "Only 3 songs have preview URLs;
minimum is 4 of 5+").

When borderline, err toward publish=true — a slightly imperfect journey is better
than suppressing good content. Only reject on hard quality failures.

Write a reviewer_note (1–3 sentences) summarising the journey quality regardless
of the publish decision. If there are unverified claims, name them.

Do not rewrite or change any content. Report only.
""".strip(),
    )
