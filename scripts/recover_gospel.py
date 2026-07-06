"""Recovery script for gospel journey — bypasses Gemini agents entirely.

Steps:
  1. Load draft (titles/artists/blurbs) from data/drafts/
  2. Fetch preview URLs directly via iTunes/Deezer (no Gemini)
  3. Merge with existing published data (keep known preview_url if re-fetch misses)
  4. Generate TTS with macOS `say`
  5. Publish to data/journeys.json
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

# Ensure src is on path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from music_journey.mcp_music.server import search_track
from music_journey.core.models import Journey, Song, StreamingLinks
from music_journey.pipeline.tts import generate_narration

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

JOURNEY_ID = "journey:it-started-with-a-choir"
DATA_DIR = Path(__file__).parent.parent / "data"
DRAFT_PATH = DATA_DIR / "drafts" / f"{JOURNEY_ID}.json"
JOURNEYS_PATH = DATA_DIR / "journeys.json"
AUDIO_DIR = DATA_DIR / "audio"


async def fetch_all_previews(songs: list[dict], existing_by_pos: dict[int, dict]) -> list[dict]:
    """Fetch preview URLs for all songs; fall back to existing published data on miss."""
    results = []
    for s in songs:
        pos = s["position"]
        title = s["title"]
        artist = s["artist"]
        logger.info("Fetching preview: %s — %s", title, artist)
        fetched = await search_track(title=title, artist=artist)
        if fetched.get("preview_url"):
            logger.info("  ✓ found via %s", fetched.get("source"))
            s["preview_url"] = fetched["preview_url"]
            s["image_url"] = fetched.get("image_url")
            links = fetched.get("streaming_links", {})
            s["streaming_links"] = {
                "spotify": links.get("spotify"),
                "apple_music": links.get("apple_music"),
                "youtube": links.get("youtube"),
            }
        else:
            # Fall back to whatever is already published
            existing = existing_by_pos.get(pos, {})
            s["preview_url"] = existing.get("preview_url")
            s["image_url"] = existing.get("image_url")
            s["streaming_links"] = existing.get("streaming_links", {"spotify": None, "apple_music": None, "youtube": None})
            if s["preview_url"]:
                logger.info("  ✓ using existing published preview_url for pos %d", pos)
            else:
                logger.warning("  ✗ no preview found for pos %d: %s", pos, title)
        results.append(s)
        await asyncio.sleep(0.3)  # be polite to iTunes API
    return results


def build_journey(draft: dict, songs_with_previews: list[dict]) -> Journey:
    song_objects = []
    for s in songs_with_previews:
        links = s.get("streaming_links") or {}
        song_objects.append(Song(
            position=s["position"],
            title=s["title"],
            artist=s["artist"],
            month_year=s.get("month_year", ""),
            place=s.get("place", ""),
            blurb=s.get("blurb"),
            blurb_audio_url=None,
            preview_url=s.get("preview_url"),
            image_url=s.get("image_url"),
            streaming_links=StreamingLinks(
                spotify=links.get("spotify"),
                apple_music=links.get("apple_music"),
                youtube=links.get("youtube"),
            ),
        ))

    return Journey(
        id=JOURNEY_ID,
        title=draft["title"],
        subtitle=draft["subtitle"],
        theme=draft.get("theme", "gospel & soul"),
        blurb=draft["blurb"],
        closing_paragraph=draft["closing_paragraph"],
        intro_audio_url=None,
        outro_audio_url=None,
        image_url=None,
        prompt_chips=[],
        songs=song_objects,
        categories=[],
    )


def publish(journey: Journey) -> None:
    journeys = json.loads(JOURNEYS_PATH.read_text())
    idx = next((i for i, j in enumerate(journeys) if j["id"] == JOURNEY_ID), None)
    entry = journey.model_dump()
    if idx is not None:
        # Preserve fields not managed by this script
        existing = journeys[idx]
        entry.setdefault("prompt_chips", existing.get("prompt_chips", []))
        entry.setdefault("categories", existing.get("categories", []))
        journeys[idx] = entry
    else:
        journeys.append(entry)
    JOURNEYS_PATH.write_text(json.dumps(journeys, indent=2, ensure_ascii=False))
    logger.info("Published %s (%d songs)", JOURNEY_ID, len(journey.songs))


def _parse_args():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--backend", choices=["gemini", "macos", "edge"], default="edge")
    return p.parse_args()


async def main() -> None:
    args = _parse_args()
    backend = args.backend
    draft = json.loads(DRAFT_PATH.read_text())

    # Load existing published data to use as fallback for previews
    journeys = json.loads(JOURNEYS_PATH.read_text())
    existing_journey = next((j for j in journeys if j["id"] == JOURNEY_ID), None)
    existing_by_pos: dict[int, dict] = {}
    if existing_journey:
        for s in existing_journey.get("songs", []):
            existing_by_pos[s["position"]] = s
        logger.info("Found existing published journey with %d songs", len(existing_by_pos))

    # Step 1: fetch previews
    songs_with_previews = await fetch_all_previews(draft["songs"], existing_by_pos)
    have_preview = sum(1 for s in songs_with_previews if s.get("preview_url"))
    logger.info("Preview coverage: %d/%d songs", have_preview, len(songs_with_previews))

    # Step 2: build Journey model
    journey = build_journey(draft, songs_with_previews)

    # Step 3: TTS
    logger.info("Generating TTS narration (%s backend)...", backend)
    journey = await generate_narration(journey, AUDIO_DIR, backend=backend)

    tts_ok = sum(1 for s in journey.songs if s.blurb_audio_url)
    logger.info("TTS: intro=%s, outro=%s, songs=%d/%d",
                bool(journey.intro_audio_url), bool(journey.outro_audio_url),
                tts_ok, len(journey.songs))

    # Step 4: publish
    publish(journey)
    logger.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
