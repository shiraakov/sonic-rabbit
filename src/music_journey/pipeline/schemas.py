"""Pydantic schemas for the content-generation pipeline.

These are the structured output types for each LlmAgent. They live separately
from core/models.py because they are pipeline-internal — they describe agent
I/O, not the final persisted Journey/Song shape.

Pipeline flow:
  SongPicker → CandidateList
  SongFetcher (all candidates) → filter to those with previews
  ContentWriter (confirmed list) → JourneyDraft
  FactChecker (confirmed songs only) → CheckerOutput per song
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ── SongPicker output (pass 1 — no blurbs yet) ───────────────────────────────

class SongCandidate(BaseModel):
    position: int
    title: str
    artist: str
    month_year: str  # best-effort; FactChecker is the authority
    place: str       # best-effort; FactChecker is the authority


class CandidateList(BaseModel):
    candidates: list[SongCandidate]  # over-generated; fetcher screens for availability


# ── ContentWriter output (pass 2 — blurbs for confirmed songs only) ──────────

class SongDraft(BaseModel):
    position: int
    title: str
    artist: str
    month_year: str
    place: str
    blurb: str  # must mention artist name, year, and place; written after preview confirmed


class JourneyDraft(BaseModel):
    title: str
    subtitle: str
    theme: str
    blurb: str             # journey-level intro (1–3 paragraphs)
    closing_paragraph: str
    songs: list[SongDraft]


# ── SongFetcher output ────────────────────────────────────────────────────────

class FetcherOutput(BaseModel):
    preview_url: Optional[str] = None
    image_url: Optional[str] = None
    streaming_links: dict[str, Optional[str]] = Field(default_factory=dict)
    source: Optional[str] = None  # "itunes" | "deezer" | None


# ── FactChecker output ────────────────────────────────────────────────────────

class ClaimCheck(BaseModel):
    claim: str
    corroborated: bool
    confidence: str       # "high" | "medium" | "low"
    source_note: str


class CheckerOutput(BaseModel):
    month_year: str        # corrected if sourced, else candidate's value
    place: str             # corrected if sourced, else candidate's value
    metadata_verified: bool
    metadata_source_note: str
    claim_checks: list[ClaimCheck]
    any_unverified_claims: bool


# ── GraphLinker output ────────────────────────────────────────────────────────

class LinkerOutput(BaseModel):
    journey_id: str
    songs_total: int
    songs_metadata_verified: int
    songs_missing_preview: int
    songs_missing_audio: int
    songs_with_unverified_claims: int
    quality_flags: list[str]
    reviewer_note: str
    publish: bool = True        # pipeline's autonomous publish decision
    rejection_reason: str = ""  # populated when publish=false
