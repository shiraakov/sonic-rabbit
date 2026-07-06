"""Service layer — headless core surface.

Pure functions over the repository. No FastAPI or ADK imports.
Methods added incrementally across M1–M5.
"""

from __future__ import annotations

import random
import re
from typing import TYPE_CHECKING

from .models import Journey, Song
from .repository import Repository

if TYPE_CHECKING:
    from ..discovery.embedder import JourneyEmbedder
    from ..discovery.demand_log import DemandLog


class Services:
    def __init__(
        self,
        repo: Repository,
        embedder: "JourneyEmbedder | None" = None,
        demand_log: "DemandLog | None" = None,
    ) -> None:
        self._repo = repo
        self._embedder = embedder
        self._demand_log = demand_log

    @property
    def embedder(self):
        return self._embedder

    def list_journeys(self) -> list[Journey]:
        return self._repo.all_journeys()

    def get_journey(self, journey_id: str) -> Journey | None:
        return self._repo.get_journey(journey_id)

    def get_journey_step(self, journey_id: str, position: int) -> Song | None:
        """Return the song at the given 1-indexed position, or None."""
        journey = self._repo.get_journey(journey_id)
        if journey is None:
            return None
        for song in journey.songs:
            if song.position == position:
                return song
        return None

    def get_playlist(self, journey_id: str) -> list[Song]:
        """All songs for a journey in position order."""
        journey = self._repo.get_journey(journey_id)
        if journey is None:
            return []
        return sorted(journey.songs, key=lambda s: s.position)

    def get_chips(self) -> list[dict]:
        """All prompt chips across all journeys, deduplicated, in stable order."""
        chips: list[dict] = []
        seen: set[str] = set()
        for journey in self._repo.all_journeys():
            for chip in journey.prompt_chips:
                if chip not in seen:
                    seen.add(chip)
                    chips.append({"label": chip, "journey_id": journey.id})
        return chips

    def get_next_journey(self, current_id: str) -> Journey | None:
        """Category overlap first, then same theme, then random. Never returns current."""
        all_journeys = self._repo.all_journeys()
        current = self._repo.get_journey(current_id)
        others = [j for j in all_journeys if j.id != current_id]
        if not others:
            return None
        if current:
            current_cats = set(current.categories or [])
            if current_cats:
                overlapping = [j for j in others if set(j.categories or []) & current_cats]
                if overlapping:
                    return random.choice(overlapping)
            same_theme = [j for j in others if j.theme == current.theme]
            if same_theme:
                return random.choice(same_theme)
        return random.choice(others)

    def get_related_journeys(self, current_id: str, limit: int = 3) -> list[Journey]:
        """Return up to `limit` journeys ordered by category overlap, never the current one."""
        all_journeys = self._repo.all_journeys()
        current = self._repo.get_journey(current_id)
        others = [j for j in all_journeys if j.id != current_id]
        if not current or not others:
            return others[:limit]
        current_cats = set(current.categories or [])
        def overlap(j: Journey) -> int:
            return len(current_cats & set(j.categories or []))
        others.sort(key=overlap, reverse=True)
        return others[:limit]

    def get_random_journey(self) -> Journey | None:
        all_journeys = self._repo.all_journeys()
        return random.choice(all_journeys) if all_journeys else None

    def search_journeys(self, query: str) -> dict:
        """Semantic search (Rung 2) when embedder available, keyword fallback otherwise.

        Returns {"journey": Journey, "score": float} on hit,
        or {"miss": True, "closest": Journey | None, "score": float} on miss.
        Miss queries are appended to demand_log if one is configured.
        """
        if self._embedder is not None:
            result = self._embedder.search(query)
        else:
            result = self._keyword_search(query)

        if result.get("miss"):
            if self._demand_log is not None:
                closest = result.get("closest")
                self._demand_log.record(query, closest.id if closest else None)

        return result

    def _keyword_search(self, query: str) -> dict:
        words = re.findall(r"\w+", query.lower())
        journeys = self._repo.all_journeys()
        if not journeys:
            return {"miss": True, "closest": None, "score": 0.0}

        def score(j: Journey) -> int:
            haystack = f"{j.title} {j.theme} {j.blurb}".lower()
            return sum(1 for w in words if w in haystack)

        scored = sorted(journeys, key=score, reverse=True)
        best = scored[0]
        if score(best) > 0:
            return {"journey": best, "score": float(score(best))}
        return {"miss": True, "closest": best, "score": 0.0}
