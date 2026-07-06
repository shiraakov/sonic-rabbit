"""
Print a journey to the terminal, step by step.

Usage:
    uv run python scripts/show_journey.py                        # list available journeys
    uv run python scripts/show_journey.py journey:great-migration
    uv run python scripts/show_journey.py journey:walk-a-mile
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from music_journey.core.config import settings
from music_journey.core.repository_json import JsonRepository
from music_journey.core.services import Services

DIVIDER = "─" * 72
THICK   = "═" * 72


def wrap(text: str, width: int = 72) -> str:
    import textwrap
    return textwrap.fill(text, width)


def main() -> None:
    repo = JsonRepository(settings.data_dir)
    repo.load()
    svc = Services(repo)

    if len(sys.argv) < 2:
        journeys = svc.list_journeys()
        print("\nAvailable journeys:\n")
        for j in journeys:
            chips = ", ".join(f'"{c}"' for c in j.prompt_chips)
            print(f"  {j.id}")
            print(f"    {j.title} — {j.subtitle}")
            print(f"    theme: {j.theme}   chips: {chips}")
            print()
        print(f"Usage: uv run python scripts/show_journey.py <journey-id>\n")
        return

    journey_id = sys.argv[1]
    journey = svc.get_journey(journey_id)
    if journey is None:
        print(f"Journey not found: {journey_id}")
        sys.exit(1)

    print(f"\n{THICK}")
    print(f"  {journey.title.upper()}")
    print(f"  {journey.subtitle}")
    print(f"  Theme: {journey.theme}")
    print(THICK)
    print()
    print(wrap(journey.blurb))
    print()

    songs = svc.get_playlist(journey_id)
    for song in songs:
        print(DIVIDER)
        preview = f"  [preview: {song.preview_url}]" if song.preview_url else "  [no preview yet]"
        print(f"  {song.position}. {song.title} — {song.artist}")
        print(f"     {song.month_year}  ·  {song.place}")
        print(preview)
        print()
        print(wrap(song.blurb))
        print()

    print(THICK)
    print(f"  End of journey — {len(songs)} songs")
    print(THICK)
    print()


if __name__ == "__main__":
    main()
