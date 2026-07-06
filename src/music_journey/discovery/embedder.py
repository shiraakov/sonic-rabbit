"""Rung-2 semantic journey search using MiniLM cosine similarity.

Requires the [discovery] optional dep group:
    uv sync --extra discovery
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.models import Journey

THRESHOLD = 0.35
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def _journey_text(journey: "Journey") -> str:
    chips = " ".join(journey.prompt_chips)
    return f"{journey.title} {journey.theme} {journey.blurb} {chips}"


class JourneyEmbedder:
    """Embed journeys at startup; cosine-match a free-text query at request time.

    Raises ImportError on construction if sentence-transformers is not installed.
    """

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]
        import numpy as np  # noqa: F401 — validate numpy is present

        self._model = SentenceTransformer(MODEL_NAME)
        self._journeys: list[Journey] = []
        self._matrix: object = None  # numpy ndarray once indexed

    def index(self, journeys: list["Journey"]) -> None:
        """Build the embedding matrix from the current journey corpus."""
        import numpy as np

        self._journeys = list(journeys)
        if not self._journeys:
            self._matrix = None
            return

        texts = [_journey_text(j) for j in self._journeys]
        self._matrix = self._model.encode(texts, normalize_embeddings=True)

    def search(self, query: str) -> dict:
        """Return closest journey by cosine similarity.

        Returns:
            {"journey": Journey, "score": float}  — hit (score >= THRESHOLD)
            {"miss": True, "closest": Journey | None, "score": float}  — miss
        """
        import numpy as np

        if not self._journeys or self._matrix is None:
            return {"miss": True, "closest": None, "score": 0.0}

        q_vec = self._model.encode([query], normalize_embeddings=True)[0]
        scores = self._matrix @ q_vec
        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])
        best_journey = self._journeys[best_idx]

        if best_score >= THRESHOLD:
            return {"journey": best_journey, "score": best_score}
        return {"miss": True, "closest": best_journey, "score": best_score}
