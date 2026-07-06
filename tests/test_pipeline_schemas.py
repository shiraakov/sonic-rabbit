"""Schema validation tests — pipeline Pydantic models and TTS helpers.

These tests don't call any external APIs or ADK agents.
"""

from __future__ import annotations

import struct

import pytest

from music_journey.pipeline.schemas import (
    CheckerOutput,
    ClaimCheck,
    FetcherOutput,
    JourneyDraft,
    LinkerOutput,
    SongDraft,
)
from music_journey.pipeline.tts import _pcm_to_wav


# ── JourneyDraft ──────────────────────────────────────────────────────────────

def test_journey_draft_parses_valid():
    data = {
        "title": "From the Delta to Detroit",
        "subtitle": "Great Migration music",
        "theme": "geopolitical movement",
        "blurb": "A journey through 60 years of Black American music.",
        "closing_paragraph": "The arc ends in Compton.",
        "songs": [
            {
                "position": 1,
                "title": "Cross Road Blues",
                "artist": "Robert Johnson",
                "month_year": "November 1936",
                "place": "San Antonio, Texas",
                "blurb": "Robert Johnson recorded this in San Antonio in November 1936.",
            }
        ],
    }
    draft = JourneyDraft.model_validate(data)
    assert draft.title == "From the Delta to Detroit"
    assert len(draft.songs) == 1
    assert draft.songs[0].position == 1


def test_song_draft_requires_all_fields():
    with pytest.raises(Exception):
        SongDraft.model_validate({"position": 1, "title": "X"})  # missing artist, etc.


def test_journey_draft_rejects_missing_blurb():
    with pytest.raises(Exception):
        JourneyDraft.model_validate({
            "title": "X", "subtitle": "", "theme": "t",
            "closing_paragraph": "", "songs": [],
        })  # missing blurb


# ── FetcherOutput ─────────────────────────────────────────────────────────────

def test_fetcher_output_all_nulls():
    out = FetcherOutput()
    assert out.preview_url is None
    assert out.source is None


def test_fetcher_output_with_data():
    out = FetcherOutput.model_validate({
        "preview_url": "https://example.com/preview.m4a",
        "image_url": "https://example.com/art.jpg",
        "streaming_links": {"apple_music": "https://music.apple.com/123"},
        "source": "itunes",
    })
    assert out.source == "itunes"
    assert out.streaming_links["apple_music"].startswith("https://")


# ── CheckerOutput ─────────────────────────────────────────────────────────────

def test_checker_output_verified():
    out = CheckerOutput.model_validate({
        "month_year": "November 1936",
        "place": "San Antonio, Texas",
        "metadata_verified": True,
        "metadata_source_note": "MusicBrainz",
        "claim_checks": [
            {"claim": "died at 27", "corroborated": True, "confidence": "high", "source_note": "Wikipedia"},
        ],
        "any_unverified_claims": False,
    })
    assert out.metadata_verified is True
    assert out.claim_checks[0].confidence == "high"


def test_checker_output_unverified_flag():
    out = CheckerOutput.model_validate({
        "month_year": "1936",
        "place": "Mississippi",
        "metadata_verified": False,
        "metadata_source_note": "not found",
        "claim_checks": [
            {"claim": "sold his soul at a crossroads", "corroborated": False, "confidence": "low", "source_note": "no source"},
        ],
        "any_unverified_claims": True,
    })
    assert out.any_unverified_claims is True
    assert out.claim_checks[0].corroborated is False


# ── LinkerOutput ──────────────────────────────────────────────────────────────

def test_linker_output_parses():
    out = LinkerOutput.model_validate({
        "journey_id": "journey:test",
        "songs_total": 8,
        "songs_metadata_verified": 7,
        "songs_missing_preview": 2,
        "songs_missing_audio": 0,
        "songs_with_unverified_claims": 1,
        "quality_flags": ["song 3: claim unverified"],
        "reviewer_note": "Mostly good.",
    })
    assert out.songs_total == 8
    assert len(out.quality_flags) == 1


# ── TTS helpers ───────────────────────────────────────────────────────────────

def test_pcm_to_wav_produces_valid_header():
    # 4 samples of silence (big-endian int16 zeros)
    raw_pcm = b"\x00\x00" * 4
    wav = _pcm_to_wav(raw_pcm)
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    assert wav[12:16] == b"fmt "
    assert wav[36:40] == b"data"


def test_pcm_to_wav_passes_bytes_through():
    # _pcm_to_wav wraps little-endian PCM bytes unchanged; no byte-swapping.
    # b"\x01\x00" read as little-endian int16 = 1.
    raw_pcm = b"\x01\x00"
    wav = _pcm_to_wav(raw_pcm)
    pcm_le = wav[44:]
    (sample,) = struct.unpack("<h", pcm_le)
    assert sample == 1


def test_pcm_to_wav_correct_data_size():
    raw_pcm = b"\x00\x00" * 100  # 100 samples
    wav = _pcm_to_wav(raw_pcm)
    # data chunk size is stored at bytes 40-43 (little-endian uint32)
    (data_size,) = struct.unpack("<I", wav[40:44])
    assert data_size == len(raw_pcm)


def test_pcm_to_wav_sample_rate_in_header():
    raw_pcm = b"\x00\x00" * 10
    wav = _pcm_to_wav(raw_pcm)
    # Sample rate at bytes 24-27
    (sample_rate,) = struct.unpack("<I", wav[24:28])
    assert sample_rate == 24000
