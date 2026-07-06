"""Miss-query demand log — append-only JSONL at data/demand_log.jsonl."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class DemandLog:
    def __init__(self, data_dir: str | Path) -> None:
        self._path = Path(data_dir) / "demand_log.jsonl"

    def record(self, query: str, closest_id: str | None) -> None:
        """Append one miss record. Creates the file if it doesn't exist."""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "query": query,
            "closest_id": closest_id,
        }
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
