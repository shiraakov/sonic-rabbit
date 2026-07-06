"""Custom MCP server — music metadata and fact-verification tools.

Exposes three tools to ADK agents:
  search_track       → SongFetcher  (iTunes primary, Deezer fallback)
  verify_recording   → FactChecker  (MusicBrainz recording date + place)
  search_wikipedia   → FactChecker  (Wikipedia extract for claim corroboration)

Run standalone for manual testing:
  uv run python -m music_journey.mcp_music.server
"""

from __future__ import annotations

import logging

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("mcp-music")

_ITUNES_SEARCH = "https://itunes.apple.com/search"
_DEEZER_SEARCH = "https://api.deezer.com/search"
_MB_RECORDING = "https://musicbrainz.org/ws/2/recording/"
_MB_RECORDING_ID = "https://musicbrainz.org/ws/2/recording/{mbid}"
_WP_SEARCH = "https://en.wikipedia.org/w/api.php"
_WP_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
_MB_HEADERS = {"User-Agent": "MusicJourneyCapstone/0.1 (https://github.com/shiraakov/sonic-rabbit)"}


@mcp.tool()
async def search_track(title: str, artist: str) -> dict:
    """Search iTunes (primary) then Deezer (fallback) for a track.

    Returns preview_url (30s snippet), image_url, streaming_links, and source.
    All fields are null on a complete miss — that is not an error.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        # iTunes
        try:
            resp = await client.get(
                _ITUNES_SEARCH,
                params={"term": f"{artist} {title}", "media": "music", "entity": "song", "limit": 5},
            )
            resp.raise_for_status()
            for r in resp.json().get("results", []):
                if r.get("previewUrl"):
                    return {
                        "preview_url": r["previewUrl"],
                        "image_url": r.get("artworkUrl100"),
                        "streaming_links": {
                            "apple_music": r.get("trackViewUrl"),
                            "spotify": None,
                            "youtube": None,
                        },
                        "source": "itunes",
                    }
        except Exception as e:
            logger.warning("iTunes search failed: %s", e)

        # Deezer fallback
        try:
            resp = await client.get(
                _DEEZER_SEARCH,
                params={"q": f"{artist} {title}", "limit": 5},
            )
            resp.raise_for_status()
            for r in resp.json().get("data", []):
                if r.get("preview"):
                    return {
                        "preview_url": r["preview"],
                        "image_url": r.get("album", {}).get("cover_medium"),
                        "streaming_links": {
                            "apple_music": None,
                            "spotify": None,
                            "youtube": None,
                        },
                        "source": "deezer",
                    }
        except Exception as e:
            logger.warning("Deezer search failed: %s", e)

    return {"preview_url": None, "image_url": None, "streaming_links": {}, "source": None}


@mcp.tool()
async def verify_recording(title: str, artist: str) -> dict:
    """Look up a recording in MusicBrainz to get authoritative recording date and place.

    Returns recording_date (ISO string or partial like "1936"), recording_place
    (studio/city name or null), mbid (MusicBrainz recording ID or null), and sources list.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            # Step 1: search for the recording
            resp = await client.get(
                _MB_RECORDING,
                params={
                    "query": f'recording:"{title}" AND artistname:"{artist}"',
                    "fmt": "json",
                    "limit": 5,
                },
                headers=_MB_HEADERS,
            )
            resp.raise_for_status()
            recordings = resp.json().get("recordings", [])
        except Exception as e:
            logger.warning("MusicBrainz search failed: %s", e)
            return {"recording_date": None, "recording_place": None, "mbid": None, "sources": []}

        if not recordings:
            return {"recording_date": None, "recording_place": None, "mbid": None, "sources": []}

        rec = recordings[0]
        mbid = rec.get("id")
        recording_date = rec.get("first-release-date")

        # Step 2: fetch place relations for the top recording
        recording_place = None
        if mbid:
            try:
                resp = await client.get(
                    _MB_RECORDING_ID.format(mbid=mbid),
                    params={"inc": "place-rels", "fmt": "json"},
                    headers=_MB_HEADERS,
                )
                resp.raise_for_status()
                data = resp.json()
                for rel in data.get("relations", []):
                    if rel.get("type") == "recorded at" and rel.get("place"):
                        recording_place = rel["place"].get("name")
                        break
            except Exception as e:
                logger.warning("MusicBrainz place lookup failed for %s: %s", mbid, e)

        sources = ["musicbrainz"]
        return {
            "recording_date": recording_date,
            "recording_place": recording_place,
            "mbid": mbid,
            "sources": sources,
        }


@mcp.tool()
async def search_wikipedia(query: str) -> dict:
    """Search Wikipedia and return the summary extract for the top result.

    Returns title, extract (first paragraph), url, and found (bool).
    Use this to corroborate specific factual claims in a song blurb.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            # Step 1: find the best matching page title
            resp = await client.get(
                _WP_SEARCH,
                params={
                    "action": "opensearch",
                    "search": query,
                    "limit": 3,
                    "format": "json",
                    "redirects": "resolve",
                },
            )
            resp.raise_for_status()
            results = resp.json()
            titles = results[1] if len(results) > 1 else []
            if not titles:
                return {"title": None, "extract": None, "url": None, "found": False}

            # Step 2: fetch the summary for the top title
            page_title = titles[0].replace(" ", "_")
            resp = await client.get(
                _WP_SUMMARY.format(title=page_title),
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "title": data.get("title"),
                "extract": data.get("extract"),
                "url": data.get("content_urls", {}).get("desktop", {}).get("page"),
                "found": True,
            }
        except Exception as e:
            logger.warning("Wikipedia search failed for %r: %s", query, e)
            return {"title": None, "extract": None, "url": None, "found": False}


if __name__ == "__main__":
    mcp.run()
