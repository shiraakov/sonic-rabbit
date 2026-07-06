"""Repository tests — JsonRepository against the two POC journeys."""

import json
import pytest

from music_journey.core.models import Journey, Song, StreamingLinks
from music_journey.core.repository_json import JsonRepository


MIGRATION_ID = "journey:great-migration"
SHOES_ID = "journey:walk-a-mile"


@pytest.fixture
def data_dir(tmp_path):
    """Temp dir with journeys.json copied from the real data file."""
    import shutil
    from pathlib import Path
    src = Path(__file__).parent.parent / "data" / "journeys.json"
    shutil.copy(src, tmp_path / "journeys.json")
    return tmp_path


@pytest.fixture
def repo(data_dir):
    r = JsonRepository(str(data_dir))
    r.load()
    return r


@pytest.fixture
def empty_repo(tmp_path):
    (tmp_path / "journeys.json").write_text("[]")
    r = JsonRepository(str(tmp_path))
    r.load()
    return r


# ── empty / missing store ──────────────────────────────────────────────────

def test_empty_store_returns_no_journeys(empty_repo):
    assert empty_repo.all_journeys() == []


def test_missing_file_loads_cleanly(tmp_path):
    r = JsonRepository(str(tmp_path))
    r.load()
    assert r.all_journeys() == []


# ── load ───────────────────────────────────────────────────────────────────

def test_loads_both_poc_journeys(repo):
    ids = {j.id for j in repo.all_journeys()}
    assert MIGRATION_ID in ids
    assert SHOES_ID in ids


def test_journey_song_count(repo):
    migration = repo.get_journey(MIGRATION_ID)
    assert migration is not None
    assert len(migration.songs) == 8

    shoes = repo.get_journey(SHOES_ID)
    assert shoes is not None
    assert len(shoes.songs) == 8


def test_songs_are_in_order(repo):
    songs = repo.get_journey(MIGRATION_ID).songs
    positions = [s.position for s in songs]
    assert positions == sorted(positions)


def test_first_song_fields(repo):
    song = repo.get_journey(MIGRATION_ID).songs[0]
    assert song.title == "Cross Road Blues"
    assert song.artist == "Robert Johnson"
    assert song.month_year == "November 1936"
    assert song.place == "San Antonio, Texas"
    assert song.blurb != ""


def test_prompt_chips_loaded(repo):
    migration = repo.get_journey(MIGRATION_ID)
    assert "Take me somewhere political" in migration.prompt_chips


# ── upsert ─────────────────────────────────────────────────────────────────

def test_upsert_new_journey(empty_repo, tmp_path):
    j = Journey(
        id="journey:test",
        title="Test Journey",
        theme="test",
        blurb="A test.",
        songs=[],
    )
    empty_repo.upsert_journey(j)
    assert empty_repo.get_journey("journey:test") is not None
    # persisted to disk
    raw = json.loads((tmp_path / "journeys.json").read_text())
    assert any(r["id"] == "journey:test" for r in raw)


def test_upsert_replaces_existing(empty_repo):
    j = Journey(id="journey:test", title="Old", theme="t", blurb=".", songs=[])
    empty_repo.upsert_journey(j)
    j2 = Journey(id="journey:test", title="New", theme="t", blurb=".", songs=[])
    empty_repo.upsert_journey(j2)
    assert empty_repo.get_journey("journey:test").title == "New"
    assert len(empty_repo.all_journeys()) == 1


def test_delete_journey(empty_repo):
    j = Journey(id="journey:del", title="Gone", theme="t", blurb=".", songs=[])
    empty_repo.upsert_journey(j)
    empty_repo.delete_journey("journey:del")
    assert empty_repo.get_journey("journey:del") is None
