"""Repository interface — the storage boundary.

Service layer and pipeline both depend on this abstract interface, not on any concrete store.
M0/M1 ship a flat-JSON implementation; swapping to SQLite later means writing one new subclass.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import Journey


class Repository(ABC):
    @abstractmethod
    def load(self) -> None:
        """Load the store into memory. Safe to call on an empty or absent store."""

    @abstractmethod
    def get_journey(self, journey_id: str) -> Journey | None: ...

    @abstractmethod
    def all_journeys(self) -> list[Journey]: ...

    @abstractmethod
    def upsert_journey(self, journey: Journey) -> None:
        """Insert or replace a journey by id."""

    @abstractmethod
    def delete_journey(self, journey_id: str) -> None: ...
