"""Pipeline orchestrator — theme string → published Journey.

Entrypoint:
    uv run python -m music_journey.pipeline.run --theme "songs about shoes"

Optional flags:
    --min-songs N     (default 6)
    --max-songs N     (default 10)
    --voice NAME      (default Kore)
    --dry-run         skip TTS and fetcher; text-only fast iteration
    --title TEXT      override the model-generated title
    --subtitle TEXT   override the model-generated subtitle
    --data-dir PATH   override data directory

Pipeline order:
  1. SongPicker      → CandidateList  (titles/artists only, ~target+4 songs)
  2. SongFetcher     → FetcherOutput  (all candidates — screens for preview availability)
  2.5 filter         → keep up to max_songs with a preview_url, in order
  3. ContentWriter   → JourneyDraft   (blurbs written for the confirmed final set)
  4. FactChecker     → CheckerOutput  (only confirmed songs — no wasted API calls)
  5. Merge + TTS + GraphLinker
  6. GraphLinker quality gate: publish if trustworthy, else save to data/review/ and return None
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

import google.genai.types as genai_types
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from ..core.config import settings
from ..core.models import Journey, Song, StreamingLinks
from ..core.repository_json import JsonRepository
from ..discovery.demand_log import DemandLog
from .agents import make_content_writer, make_fact_checker, make_graph_linker, make_song_fetcher, make_song_picker
from .schemas import CandidateList, CheckerOutput, FetcherOutput, JourneyDraft, LinkerOutput, SongCandidate, SongDraft
from .tts import TtsBackend, generate_narration

logger = logging.getLogger(__name__)


# ── Runner helper ─────────────────────────────────────────────────────────────

async def _run_agent(agent, prompt: str) -> Any:
    """Run an agent with a single prompt and return its output_key value."""
    session_service = InMemorySessionService()
    runner = Runner(agent=agent, app_name="music_journey", session_service=session_service)
    session = await session_service.create_session(app_name="music_journey", user_id="pipeline")
    async for _ in runner.run_async(
        user_id="pipeline",
        session_id=session.id,
        new_message=genai_types.Content(
            role="user", parts=[genai_types.Part(text=prompt)]
        ),
    ):
        pass
    final_session = await session_service.get_session(
        app_name="music_journey", user_id="pipeline", session_id=session.id
    )
    return final_session.state.get(agent.output_key)


# ── Journey ID generation ─────────────────────────────────────────────────────

def _make_journey_id(title: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return f"journey:{slug}"


# ── Merge helpers ─────────────────────────────────────────────────────────────

def _build_journey(
    draft: JourneyDraft,
    journey_id: str,
    fetcher_results: dict[int, FetcherOutput],
    checker_results: dict[int, CheckerOutput],
) -> Journey:
    songs: list[Song] = []
    for sd in draft.songs:
        fetched = fetcher_results.get(sd.position, FetcherOutput())
        checked = checker_results.get(sd.position, CheckerOutput(
            month_year=sd.month_year,
            place=sd.place,
            metadata_verified=False,
            metadata_source_note="not checked",
            claim_checks=[],
            any_unverified_claims=False,
        ))
        songs.append(Song(
            position=sd.position,
            title=sd.title,
            artist=sd.artist,
            month_year=checked.month_year,
            place=checked.place,
            blurb=sd.blurb,
            preview_url=fetched.preview_url,
            image_url=fetched.image_url,
            streaming_links=StreamingLinks(
                apple_music=fetched.streaming_links.get("apple_music"),
                spotify=fetched.streaming_links.get("spotify"),
                youtube=fetched.streaming_links.get("youtube"),
            ),
        ))

    return Journey(
        id=journey_id,
        title=draft.title,
        subtitle=draft.subtitle,
        theme=draft.theme,
        blurb=draft.blurb,
        closing_paragraph=draft.closing_paragraph,
        songs=songs,
    )


# ── Draft print ───────────────────────────────────────────────────────────────

def _print_draft(draft: JourneyDraft) -> None:
    sep = "─" * 60
    print(f"\n{sep}")
    print(f"  {draft.title}")
    print(f"  {draft.subtitle}")
    print(f"  Theme: {draft.theme}")
    print(sep)
    print(f"\n{draft.blurb}\n")
    for s in draft.songs:
        print(f"  [{s.position}] {s.title} — {s.artist} ({s.month_year}, {s.place})")
        print(f"      {s.blurb}\n")
    print(f"Closing: {draft.closing_paragraph}")
    print(sep)


# ── Main pipeline ─────────────────────────────────────────────────────────────

async def run_pipeline(
    theme: str,
    min_songs: int = 6,
    max_songs: int = 10,
    voice: str = "Kore",
    dry_run: bool = False,
    title: Optional[str] = None,
    subtitle: Optional[str] = None,
    data_dir: Optional[Path] = None,
    tts_backend: TtsBackend = "kokoro",
) -> Optional[Journey]:
    resolved = Path(data_dir or settings.data_dir)
    drafts_dir = resolved / "drafts"
    review_dir = resolved / "review"

    # gemini-2.5-flash free tier = 15 RPM. Serial with 5s sleep stays safely under.
    _sem = asyncio.Semaphore(1)

    async def _fetch_candidate(c: SongCandidate) -> tuple[int, FetcherOutput]:
        async with _sem:
            fetcher = make_song_fetcher()
            raw = await _run_agent(fetcher, f"Fetch metadata for: title='{c.title}', artist='{c.artist}'")
            await asyncio.sleep(5)
        if raw is None:
            return c.position, FetcherOutput()
        if isinstance(raw, dict):
            return c.position, FetcherOutput.model_validate(raw)
        return c.position, raw

    async def _check_song(sd: SongDraft) -> tuple[int, CheckerOutput]:
        async with _sem:
            checker = make_fact_checker()
            prompt = (
                f"Fact-check this song entry:\n"
                f"Title: {sd.title}\n"
                f"Artist: {sd.artist}\n"
                f"month_year: {sd.month_year}\n"
                f"place: {sd.place}\n"
                f"blurb: {sd.blurb}"
            )
            raw = await _run_agent(checker, prompt)
            await asyncio.sleep(5)
        if raw is None:
            return sd.position, CheckerOutput(
                month_year=sd.month_year,
                place=sd.place,
                metadata_verified=False,
                metadata_source_note="agent returned no output",
                claim_checks=[],
                any_unverified_claims=False,
            )
        if isinstance(raw, dict):
            return sd.position, CheckerOutput.model_validate(raw)
        return sd.position, raw

    # ── Load saved draft or run full generation ───────────────────────────────
    # If a draft exists for this title (saved by a previous run), reload it and
    # skip straight to fact-checking — avoids repeating expensive content generation.

    draft_file = drafts_dir / f"{_make_journey_id(title)}.json" if title else None

    if draft_file and draft_file.exists():
        # Draft already has confirmed songs with previews — skip straight to fact-checking
        logger.info("Loading saved draft from %s", draft_file)
        draft = JourneyDraft.model_validate_json(draft_file.read_text())
        journey_id = _make_journey_id(draft.title)

        # Re-fetch to get fresh preview URLs (iTunes links expire)
        fetcher_results: dict[int, FetcherOutput] = {}
        if not dry_run:
            logger.info("Step 2 (re-fetch): %d songs", len(draft.songs))
            candidates = [
                SongCandidate(position=s.position, title=s.title, artist=s.artist,
                              month_year=s.month_year, place=s.place)
                for s in draft.songs
            ]
            fetch_tasks = [_fetch_candidate(c) for c in candidates]
            fetch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
            for r in fetch_results:
                if not isinstance(r, Exception):
                    pos, out = r
                    fetcher_results[pos] = out
                else:
                    logger.warning("Fetch failed: %s", r)

    else:
        # ── Step 1: SongPicker ────────────────────────────────────────────────
        target = min_songs + 4  # over-generate so the fetcher has extras to screen
        logger.info("Step 1: SongPicker — theme=%r, requesting %d candidates", theme, target)
        picker = make_song_picker()
        raw_candidates = await _run_agent(
            picker,
            f"Theme: {theme}\nTarget song count: {min_songs}–{max_songs} (generate {target} candidates)",
        )
        if raw_candidates is None:
            raise RuntimeError("SongPicker returned no output")
        candidate_list: CandidateList = (
            CandidateList.model_validate(raw_candidates)
            if isinstance(raw_candidates, dict)
            else raw_candidates
        )
        logger.info("SongPicker proposed %d candidates", len(candidate_list.candidates))

        # ── Step 2: SongFetcher (all candidates) ─────────────────────────────
        fetcher_results = {}
        if not dry_run:
            logger.info("Step 2: SongFetcher — screening %d candidates for previews", len(candidate_list.candidates))
            fetch_tasks = [_fetch_candidate(c) for c in candidate_list.candidates]
            fetch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
            for r in fetch_results:
                if not isinstance(r, Exception):
                    pos, out = r
                    fetcher_results[pos] = out
                else:
                    logger.warning("Fetch failed: %s", r)

        # ── Step 2.5: Filter to songs with previews ───────────────────────────
        confirmed: list[SongCandidate] = [
            c for c in candidate_list.candidates
            if fetcher_results.get(c.position, FetcherOutput()).preview_url
        ][:max_songs]

        if dry_run:
            # dry-run: accept all candidates up to max_songs (no fetcher ran)
            confirmed = candidate_list.candidates[:max_songs]

        if len(confirmed) < min_songs:
            logger.warning(
                "Only %d of %d candidates have previews — proceeding with fewer songs than target",
                len(confirmed), len(candidate_list.candidates),
            )

        # Reassign positions to be contiguous 1-N after filtering
        confirmed = [
            SongCandidate(position=i + 1, title=c.title, artist=c.artist,
                          month_year=c.month_year, place=c.place)
            for i, c in enumerate(confirmed)
        ]
        # Remap fetcher_results to the new positions
        old_to_new = {old.position: new.position for old, new in zip(
            [c for c in candidate_list.candidates
             if fetcher_results.get(c.position, FetcherOutput()).preview_url][:max_songs],
            confirmed,
        )}
        fetcher_results = {
            old_to_new[old_pos]: result
            for old_pos, result in fetcher_results.items()
            if old_pos in old_to_new
        }

        logger.info("Step 2.5: %d songs confirmed with previews", len(confirmed))

        # ── Step 3: ContentWriter (blurbs for confirmed set) ─────────────────
        logger.info("Step 3: ContentWriter — writing content for %d confirmed songs", len(confirmed))
        song_list_text = "\n".join(
            f"{c.position}. \"{c.title}\" by {c.artist} ({c.month_year}, recorded in {c.place})"
            for c in confirmed
        )
        writer = make_content_writer()
        raw_draft = await _run_agent(
            writer,
            f"Theme: {theme}\n\nConfirmed songs (in order):\n{song_list_text}",
        )
        if raw_draft is None:
            raise RuntimeError("ContentWriter returned no output")
        draft: JourneyDraft = (
            JourneyDraft.model_validate(raw_draft)
            if isinstance(raw_draft, dict)
            else raw_draft
        )

        if title:
            draft = draft.model_copy(update={"title": title})
        if subtitle:
            draft = draft.model_copy(update={"subtitle": subtitle})

        journey_id = _make_journey_id(draft.title)

    logger.info("Journey: %r (%d songs)", journey_id, len(draft.songs))

    # ── Step 4: FactChecker (confirmed songs only) ────────────────────────────
    checker_results: dict[int, CheckerOutput] = {}
    if not dry_run:
        logger.info("Step 4: FactChecker — %d songs", len(draft.songs))
        check_tasks = [_check_song(sd) for sd in draft.songs]
        check_results = await asyncio.gather(*check_tasks, return_exceptions=True)
        for r in check_results:
            if not isinstance(r, Exception):
                pos, out = r
                checker_results[pos] = out
            else:
                logger.warning("FactChecker failed: %s", r)

    # ── Step 5: Merge ─────────────────────────────────────────────────────────
    logger.info("Step 5: merging results")
    journey = _build_journey(draft, journey_id, fetcher_results, checker_results)

    # ── Step 6: TTS ───────────────────────────────────────────────────────────
    if not dry_run:
        logger.info("Step 6: NarrationGenerator — TTS (%s)", tts_backend)
        audio_dir = resolved / "audio"
        journey = await generate_narration(journey, audio_dir, voice=voice, backend=tts_backend)

    # ── Step 7: GraphLinker — quality gate + conditional publish ──────────────
    logger.info("Step 7: GraphLinker — quality gate")
    linker = make_graph_linker()
    raw_linker = await _run_agent(
        linker,
        f"Quality-check and decide whether to publish this journey:\n{journey.model_dump_json(indent=2)}",
    )

    linker_output: Optional[LinkerOutput] = None
    if raw_linker is not None:
        linker_output = (
            LinkerOutput.model_validate(raw_linker)
            if isinstance(raw_linker, dict)
            else raw_linker
        )

    # Determine whether to publish
    if linker_output is not None:
        should_publish = linker_output.publish
        publish_reason = linker_output.rejection_reason or linker_output.reviewer_note
    else:
        # Linker failed — apply deterministic fallback thresholds
        songs_with_preview = sum(1 for s in journey.songs if s.preview_url)
        songs_with_audio = sum(1 for s in journey.songs if s.blurb_audio_url)
        should_publish = (
            len(journey.songs) >= 5
            and songs_with_preview == len(journey.songs)
            and songs_with_audio >= len(journey.songs) // 2
        )
        publish_reason = (
            f"GraphLinker unavailable; fallback: {songs_with_preview}/{len(journey.songs)} "
            f"songs have previews, {songs_with_audio} have audio"
        )

    # Always write quality report
    review_dir.mkdir(parents=True, exist_ok=True)
    review_path = review_dir / f"{journey_id}.json"
    report: dict = {
        "journey_id": journey_id,
        "published": should_publish,
        "publish_reason": publish_reason,
        **(linker_output.model_dump() if linker_output else {}),
        "checker_details": {pos: checker_results[pos].model_dump() for pos in checker_results},
    }
    review_path.write_text(json.dumps(report, indent=2))

    if not should_publish:
        logger.warning(
            "Journey %r NOT published — quality gate rejected: %s",
            journey_id, publish_reason,
        )
        # Save rejected journey for inspection
        drafts_dir.mkdir(parents=True, exist_ok=True)
        (drafts_dir / f"{journey_id}.json").write_text(journey.model_dump_json(indent=2))
        return None

    repo = JsonRepository(str(resolved))
    repo.load()
    repo.upsert_journey(journey)
    logger.info("Published journey %r — %s", journey_id, publish_reason)
    return journey


# ── CLI entrypoint ────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Generate a music journey from a theme")
    parser.add_argument("--theme", required=True)
    parser.add_argument("--min-songs", type=int, default=6)
    parser.add_argument("--max-songs", type=int, default=10)
    parser.add_argument("--voice", default="Kore")
    parser.add_argument("--dry-run", action="store_true", help="Skip TTS and SongFetcher")
    parser.add_argument("--title", default=None)
    parser.add_argument("--subtitle", default=None)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--tts-backend", default="kokoro", choices=["kokoro", "edge", "gemini", "macos"],
                        help="TTS engine: kokoro (default, WAV, local), edge (MP3, no key), gemini (WAV, requires API key), macos (WAV, uses `say`)")
    args = parser.parse_args()

    journey = asyncio.run(run_pipeline(
        theme=args.theme,
        min_songs=args.min_songs,
        max_songs=args.max_songs,
        voice=args.voice,
        dry_run=args.dry_run,
        title=args.title,
        subtitle=args.subtitle,
        data_dir=Path(args.data_dir) if args.data_dir else None,
        tts_backend=args.tts_backend,
    ))
    if journey is None:
        print("\nDraft saved.")
    else:
        print(f"\nDone: {journey.id} — {journey.title} ({len(journey.songs)} songs)")


if __name__ == "__main__":
    main()
