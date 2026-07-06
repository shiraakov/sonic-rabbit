"""Journey request queue — file-backed, single-worker asyncio background task.

Queue file: {data_dir}/requests/queue.json
One request processed at a time; checks for new work every 60 seconds.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class QueueManager:
    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "requests" / "queue.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    def _load(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            return json.loads(self._path.read_text())
        except Exception:
            return []

    def _save(self, entries: list[dict]) -> None:
        self._path.write_text(json.dumps(entries, indent=2))

    async def enqueue(self, title: str, description: str, theme: str, category: str) -> str:
        entry_id = str(uuid.uuid4())[:8]
        entry = {
            "id": entry_id,
            "title": title,
            "description": description,
            "theme": theme,
            "category": category,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
            "journey_id": None,
            "error": None,
        }
        async with self._lock:
            entries = self._load()
            entries.append(entry)
            self._save(entries)
        logger.info("Queue: enqueued %s — %r", entry_id, title)
        return entry_id

    async def pending_count(self) -> int:
        async with self._lock:
            return sum(1 for e in self._load() if e["status"] == "pending")

    async def _pop_next_pending(self) -> Optional[dict]:
        async with self._lock:
            entries = self._load()
            for e in entries:
                if e["status"] == "pending":
                    e["status"] = "processing"
                    self._save(entries)
                    return dict(e)
        return None

    async def _mark_done(self, entry_id: str, journey_id: str) -> None:
        async with self._lock:
            entries = self._load()
            for e in entries:
                if e["id"] == entry_id:
                    e["status"] = "done"
                    e["journey_id"] = journey_id
                    break
            self._save(entries)

    async def _mark_failed(self, entry_id: str, error: str) -> None:
        async with self._lock:
            entries = self._load()
            for e in entries:
                if e["id"] == entry_id:
                    e["status"] = "failed"
                    e["error"] = error[:500]
                    break
            self._save(entries)


async def queue_worker(queue: QueueManager, data_dir: Path, repo, embedder) -> None:
    """Background task: process one queued journey request at a time, polling every 60s."""
    from ..pipeline.run import run_pipeline

    logger.info("Queue worker started")
    while True:
        await asyncio.sleep(60)
        entry = await queue._pop_next_pending()
        if entry is None:
            continue

        logger.info("Queue: processing %s — %r", entry["id"], entry["title"])
        try:
            journey = await run_pipeline(
                theme=entry["theme"],
                title=entry["title"] or None,
                data_dir=data_dir,
            )
            if journey is not None:
                await queue._mark_done(entry["id"], journey.id)
                repo.load()
                if embedder is not None:
                    embedder.index(repo.all_journeys())
                logger.info("Queue: completed %s → %s", entry["id"], journey.id)
            else:
                await queue._mark_failed(entry["id"], "pipeline returned None")
        except Exception as e:
            logger.exception("Queue: request %s failed", entry["id"])
            await queue._mark_failed(entry["id"], str(e))
