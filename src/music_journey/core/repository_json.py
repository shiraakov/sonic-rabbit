"""Flat-JSON repository — loads data/journeys.json into memory."""

from __future__ import annotations

import json
from pathlib import Path

from .models import Journey
from .repository import Repository


class JsonRepository(Repository):
    def __init__(self, data_dir: str = "data") -> None:
        self._path = Path(data_dir) / "journeys.json"
        self._journeys: dict[str, Journey] = {}

    def load(self) -> None:
        if not self._path.exists():
            return
        records = json.loads(self._path.read_text())
        self._journeys = {r["id"]: Journey(**r) for r in records}

    def get_journey(self, journey_id: str) -> Journey | None:
        return self._journeys.get(journey_id)

    def all_journeys(self) -> list[Journey]:
        return list(self._journeys.values())

    def upsert_journey(self, journey: Journey) -> None:
        self._journeys[journey.id] = journey
        self._persist()

    def delete_journey(self, journey_id: str) -> None:
        self._journeys.pop(journey_id, None)
        self._persist()

    def _persist(self) -> None:
        self._path.write_text(
            json.dumps([j.model_dump() for j in self._journeys.values()], indent=2)
        )
