"""Unit tests for the custom MCP server tools.

Each tool is tested with mocked HTTP responses so no real API calls are made.
Tests verify: correct endpoint called, correct parsing of response, fallback
behaviour on miss or error.

Run with: uv run python -m pytest tests/test_mcp_server.py -v
"""

from __future__ import annotations

import re

import httpx
import pytest
from pytest_httpx import HTTPXMock

from music_journey.mcp_music.server import search_track, verify_recording, search_wikipedia

_ITUNES = re.compile(r"https://itunes\.apple\.com/.*")
_DEEZER = re.compile(r"https://api\.deezer\.com/.*")
_MB_SEARCH = re.compile(r"https://musicbrainz\.org/ws/2/recording/\?.*")
_MB_DETAIL = re.compile(r"https://musicbrainz\.org/ws/2/recording/mb-.*")
_WP_OPEN = re.compile(r"https://en\.wikipedia\.org/w/api\.php.*")
_WP_SUMMARY = re.compile(r"https://en\.wikipedia\.org/api/rest_v1/.*")


# ── search_track ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_track_itunes_hit(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=_ITUNES,
        json={
            "resultCount": 1,
            "results": [{
                "trackName": "Cross Road Blues",
                "artistName": "Robert Johnson",
                "previewUrl": "https://audio.example.com/preview.m4a",
                "artworkUrl100": "https://img.example.com/art.jpg",
                "trackViewUrl": "https://music.apple.com/album/123",
            }],
        },
    )
    result = await search_track("Cross Road Blues", "Robert Johnson")
    assert result["preview_url"] == "https://audio.example.com/preview.m4a"
    assert result["image_url"] == "https://img.example.com/art.jpg"
    assert result["streaming_links"]["apple_music"] == "https://music.apple.com/album/123"
    assert result["source"] == "itunes"


@pytest.mark.asyncio
async def test_search_track_itunes_miss_falls_back_to_deezer(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=_ITUNES, json={"resultCount": 0, "results": []})
    httpx_mock.add_response(
        url=_DEEZER,
        json={
            "data": [{
                "title": "Cross Road Blues",
                "preview": "https://cdns-preview.deezer.com/preview.mp3",
                "link": "https://www.deezer.com/track/123",
                "album": {"cover_medium": "https://api.deezer.com/album/123/image"},
            }],
        },
    )
    result = await search_track("Cross Road Blues", "Robert Johnson")
    assert result["preview_url"] == "https://cdns-preview.deezer.com/preview.mp3"
    assert result["source"] == "deezer"


@pytest.mark.asyncio
async def test_search_track_complete_miss(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=_ITUNES, json={"resultCount": 0, "results": []})
    httpx_mock.add_response(url=_DEEZER, json={"data": []})
    result = await search_track("Totally Unknown Song", "Nonexistent Artist")
    assert result["preview_url"] is None
    assert result["source"] is None


@pytest.mark.asyncio
async def test_search_track_itunes_error_falls_back(httpx_mock: HTTPXMock):
    httpx_mock.add_exception(url=_ITUNES, exception=httpx.ConnectError("timeout"))
    httpx_mock.add_response(
        url=_DEEZER,
        json={"data": [{"title": "X", "preview": "https://deezer.com/p.mp3", "link": "x", "album": {"cover_medium": "y"}}]},
    )
    result = await search_track("X", "Y")
    assert result["source"] == "deezer"


# ── verify_recording ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verify_recording_returns_date_and_place(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=_MB_SEARCH,
        json={
            "recordings": [{
                "id": "mb-abc-123",
                "title": "Cross Road Blues",
                "first-release-date": "1936-11",
            }]
        },
    )
    httpx_mock.add_response(
        url=_MB_DETAIL,
        json={
            "id": "mb-abc-123",
            "relations": [{
                "type": "recorded at",
                "place": {"name": "Gunter Hotel, San Antonio"},
            }],
        },
    )
    result = await verify_recording("Cross Road Blues", "Robert Johnson")
    assert result["recording_date"] == "1936-11"
    assert "San Antonio" in result["recording_place"]
    assert result["mbid"] == "mb-abc-123"
    assert "musicbrainz" in result["sources"]


@pytest.mark.asyncio
async def test_verify_recording_no_musicbrainz_entry(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=_MB_SEARCH, json={"recordings": []})
    result = await verify_recording("Nonexistent Song", "Nobody")
    assert result["recording_date"] is None
    assert result["recording_place"] is None
    assert result["mbid"] is None


@pytest.mark.asyncio
async def test_verify_recording_place_not_in_relations(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=_MB_SEARCH,
        json={"recordings": [{"id": "mb-xyz", "title": "X", "first-release-date": "1954"}]},
    )
    httpx_mock.add_response(
        url=re.compile(r"https://musicbrainz\.org/ws/2/recording/mb-xyz.*"),
        json={"id": "mb-xyz", "relations": []},
    )
    result = await verify_recording("X", "Y")
    assert result["recording_date"] == "1954"
    assert result["recording_place"] is None


@pytest.mark.asyncio
async def test_verify_recording_api_error_returns_nulls(httpx_mock: HTTPXMock):
    httpx_mock.add_exception(
        url=re.compile(r"https://musicbrainz\.org/.*"),
        exception=httpx.ConnectError("unreachable"),
    )
    result = await verify_recording("X", "Y")
    assert result["recording_date"] is None


# ── search_wikipedia ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_wikipedia_returns_extract(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=_WP_OPEN,
        json=["Robert Johnson", ["Robert Johnson (musician)"], ["Blues musician"], ["https://en.wikipedia.org/..."]],
    )
    httpx_mock.add_response(
        url=_WP_SUMMARY,
        json={
            "title": "Robert Johnson (musician)",
            "extract": "Robert Johnson was an American blues singer-songwriter.",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Robert_Johnson_(musician)"}},
        },
    )
    result = await search_wikipedia("Robert Johnson blues musician")
    assert result["found"] is True
    assert "blues" in result["extract"].lower()
    assert result["url"].startswith("https://")


@pytest.mark.asyncio
async def test_search_wikipedia_no_results(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=_WP_OPEN, json=["zzz", [], [], []])
    result = await search_wikipedia("xyzzy quantum dinosaurs")
    assert result["found"] is False
    assert result["extract"] is None


@pytest.mark.asyncio
async def test_search_wikipedia_api_error(httpx_mock: HTTPXMock):
    httpx_mock.add_exception(
        url=re.compile(r"https://en\.wikipedia\.org/.*"),
        exception=httpx.ConnectError("unreachable"),
    )
    result = await search_wikipedia("anything")
    assert result["found"] is False
