"""Tests for M3 discovery — embedder + demand log.

Semantic tests are skipped if sentence-transformers is not installed.
Run with: uv run python -m pytest tests/test_discovery.py
Or with the full suite: uv sync --extra discovery && uv run python -m pytest
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from music_journey.core.repository_json import JsonRepository
from music_journey.core.services import Services
from music_journey.discovery.demand_log import DemandLog

sentence_transformers = pytest.importorskip(
    "sentence_transformers",
    reason="sentence-transformers not installed (uv sync --extra discovery)",
)

from music_journey.discovery.embedder import JourneyEmbedder  # noqa: E402


MIGRATION_ID = "journey:great-migration"
SHOES_ID = "journey:walk-a-mile"


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def journeys():
    src = Path(__file__).parent.parent / "data" / "journeys.json"
    from music_journey.core.repository_json import JsonRepository
    import tempfile, shutil as sh
    with tempfile.TemporaryDirectory() as td:
        sh.copy(src, Path(td) / "journeys.json")
        repo = JsonRepository(td)
        repo.load()
        yield repo.all_journeys()


@pytest.fixture(scope="module")
def embedder(journeys):
    e = JourneyEmbedder()
    e.index(journeys)
    return e


@pytest.fixture
def svc_with_embedder(tmp_path, embedder):
    src = Path(__file__).parent.parent / "data" / "journeys.json"
    shutil.copy(src, tmp_path / "journeys.json")
    repo = JsonRepository(str(tmp_path))
    repo.load()
    demand_log = DemandLog(tmp_path)
    return Services(repo, embedder=embedder, demand_log=demand_log), tmp_path


# ── JourneyEmbedder unit tests ────────────────────────────────────────────────


def test_embedder_index_builds_matrix(journeys):
    e = JourneyEmbedder()
    e.index(journeys)
    assert e._matrix is not None
    assert e._matrix.shape[0] == len(journeys)


def test_embedder_empty_corpus_returns_miss():
    e = JourneyEmbedder()
    e.index([])
    result = e.search("great migration blues")
    assert result.get("miss") is True
    assert result["closest"] is None


def test_embedder_hit_returns_journey_and_score(embedder):
    result = embedder.search("blues delta great migration")
    assert "journey" in result
    assert isinstance(result["score"], float)
    assert result["score"] >= 0.35


def test_embedder_hit_migration_query(embedder):
    result = embedder.search("great migration black music chicago delta blues")
    assert result.get("journey") is not None
    assert result["journey"].id == MIGRATION_ID


def test_embedder_hit_shoes_query(embedder):
    result = embedder.search("sneakers shoes fashion")
    assert result.get("journey") is not None
    assert result["journey"].id == SHOES_ID


def test_embedder_miss_returns_miss_flag(embedder):
    result = embedder.search("zzzzz completely unrelated qqqqq")
    assert result.get("miss") is True
    assert result.get("closest") is not None


def test_embedder_miss_score_below_threshold(embedder):
    result = embedder.search("zzzzz completely unrelated qqqqq")
    assert result["score"] < 0.35


def test_embedder_returns_only_valid_journeys(journeys, embedder):
    valid_ids = {j.id for j in journeys}
    for query in ["jazz", "rhythm blues", "hip hop street"]:
        result = embedder.search(query)
        j = result.get("journey") or result.get("closest")
        if j is not None:
            assert j.id in valid_ids


# ── DemandLog tests ───────────────────────────────────────────────────────────


def test_demand_log_creates_file_on_first_write(tmp_path):
    log = DemandLog(tmp_path)
    assert not (tmp_path / "demand_log.jsonl").exists()
    log.record("dinosaurs", None)
    assert (tmp_path / "demand_log.jsonl").exists()


def test_demand_log_writes_valid_jsonl(tmp_path):
    log = DemandLog(tmp_path)
    log.record("quantum physics", "journey:great-migration")
    lines = (tmp_path / "demand_log.jsonl").read_text().strip().split("\n")
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["query"] == "quantum physics"
    assert entry["closest_id"] == "journey:great-migration"
    assert "ts" in entry


def test_demand_log_appends_multiple_records(tmp_path):
    log = DemandLog(tmp_path)
    log.record("first query", None)
    log.record("second query", "journey:walk-a-mile")
    lines = (tmp_path / "demand_log.jsonl").read_text().strip().split("\n")
    assert len(lines) == 2


# ── Services with semantic search ────────────────────────────────────────────


def test_services_semantic_hit(svc_with_embedder):
    svc, _ = svc_with_embedder
    result = svc.search_journeys("great migration black music chicago delta blues")
    assert not result.get("miss")
    assert result["journey"].id == MIGRATION_ID


def test_services_semantic_miss_writes_demand_log(svc_with_embedder):
    svc, tmp_path = svc_with_embedder
    result = svc.search_journeys("zzzzz completely unrelated qqqqq")
    assert result.get("miss") is True
    log_path = tmp_path / "demand_log.jsonl"
    assert log_path.exists()
    entry = json.loads(log_path.read_text().strip().split("\n")[-1])
    assert entry["query"] == "zzzzz completely unrelated qqqqq"


def test_services_miss_no_demand_log_does_not_crash(tmp_path):
    src = Path(__file__).parent.parent / "data" / "journeys.json"
    shutil.copy(src, tmp_path / "journeys.json")
    repo = JsonRepository(str(tmp_path))
    repo.load()
    # No demand_log wired in
    e = JourneyEmbedder()
    e.index(repo.all_journeys())
    svc = Services(repo, embedder=e, demand_log=None)
    result = svc.search_journeys("zzzzz completely unrelated qqqqq")
    assert result.get("miss") is True
