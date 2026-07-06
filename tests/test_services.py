"""Service layer tests against the two POC journeys."""

import shutil
from pathlib import Path

import pytest

from music_journey.core.repository_json import JsonRepository
from music_journey.core.services import Services


MIGRATION_ID = "journey:great-migration"
SHOES_ID = "journey:walk-a-mile"


@pytest.fixture
def svc(tmp_path):
    src = Path(__file__).parent.parent / "data" / "journeys.json"
    shutil.copy(src, tmp_path / "journeys.json")
    repo = JsonRepository(str(tmp_path))
    repo.load()
    return Services(repo)


# ── list_journeys ──────────────────────────────────────────────────────────

def test_list_journeys_returns_both(svc):
    ids = {j.id for j in svc.list_journeys()}
    assert MIGRATION_ID in ids
    assert SHOES_ID in ids


# ── get_journey ────────────────────────────────────────────────────────────

def test_get_journey_returns_correct(svc):
    j = svc.get_journey(MIGRATION_ID)
    assert j is not None
    assert j.title == "What the South Sent North"


def test_get_journey_unknown_returns_none(svc):
    assert svc.get_journey("journey:does-not-exist") is None


def test_get_journey_has_theme_and_blurb(svc):
    j = svc.get_journey(SHOES_ID)
    assert j.theme == "one object across the decades"
    assert len(j.blurb) > 50


# ── get_journey_step ───────────────────────────────────────────────────────

def test_get_step_first_song(svc):
    song = svc.get_journey_step(MIGRATION_ID, 1)
    assert song is not None
    assert song.title == "Cross Road Blues"
    assert song.position == 1


def test_get_step_last_song(svc):
    song = svc.get_journey_step(MIGRATION_ID, 8)
    assert song is not None
    assert song.title == "Alright"
    assert song.artist == "Kendrick Lamar"


def test_get_step_out_of_range_returns_none(svc):
    assert svc.get_journey_step(MIGRATION_ID, 99) is None


def test_get_step_unknown_journey_returns_none(svc):
    assert svc.get_journey_step("journey:nope", 1) is None


def test_each_step_has_blurb(svc):
    for pos in range(1, 9):
        song = svc.get_journey_step(SHOES_ID, pos)
        assert song is not None
        assert len(song.blurb) > 50, f"song {pos} blurb too short"


# ── get_playlist ───────────────────────────────────────────────────────────

def test_playlist_returns_all_songs(svc):
    songs = svc.get_playlist(MIGRATION_ID)
    assert len(songs) == 8


def test_playlist_is_ordered(svc):
    songs = svc.get_playlist(MIGRATION_ID)
    positions = [s.position for s in songs]
    assert positions == list(range(1, 9))


def test_playlist_unknown_journey_returns_empty(svc):
    assert svc.get_playlist("journey:nope") == []


def test_shoes_playlist_arc(svc):
    songs = svc.get_playlist(SHOES_ID)
    assert songs[0].title == "Blue Suede Shoes"
    assert songs[-1].title == "Walking in My Shoes"


# ── get_chips ──────────────────────────────────────────────────────────────

def test_chips_returns_list(svc):
    chips = svc.get_chips()
    assert isinstance(chips, list)
    assert len(chips) > 0


def test_chips_have_label_and_journey_id(svc):
    for chip in svc.get_chips():
        assert "label" in chip
        assert "journey_id" in chip


def test_chips_are_deduplicated(svc):
    chips = svc.get_chips()
    labels = [c["label"] for c in chips]
    assert len(labels) == len(set(labels))


def test_chips_map_to_valid_journeys(svc):
    valid_ids = {j.id for j in svc.list_journeys()}
    for chip in svc.get_chips():
        assert chip["journey_id"] in valid_ids


def test_political_chip_maps_to_migration(svc):
    chips = {c["label"]: c["journey_id"] for c in svc.get_chips()}
    assert chips.get("Take me somewhere political") == MIGRATION_ID


# ── get_next_journey ───────────────────────────────────────────────────────

def test_next_journey_never_returns_current(svc):
    for _ in range(10):
        nxt = svc.get_next_journey(MIGRATION_ID)
        assert nxt is not None
        assert nxt.id != MIGRATION_ID


def test_next_journey_from_unknown_returns_random(svc):
    nxt = svc.get_next_journey("journey:does-not-exist")
    assert nxt is not None


def test_next_journey_none_when_only_one(tmp_path):
    import json
    from music_journey.core.models import Journey
    single = [Journey(id="journey:only", title="Only", theme="t", blurb="b.", songs=[])]
    (tmp_path / "journeys.json").write_text(
        json.dumps([j.model_dump() for j in single])
    )
    repo = JsonRepository(str(tmp_path))
    repo.load()
    svc = Services(repo)
    assert svc.get_next_journey("journey:only") is None


# ── search_journeys ────────────────────────────────────────────────────────

def test_search_hit_returns_journey(svc):
    result = svc.search_journeys("political protest migration")
    assert not result.get("miss")
    assert result["journey"].id == MIGRATION_ID


def test_search_hit_has_positive_score(svc):
    result = svc.search_journeys("shoes boots walking")
    assert result.get("score", 0) > 0


def test_search_miss_returns_miss_flag(svc):
    result = svc.search_journeys("dinosaurs quantum physics")
    assert result.get("miss") is True


def test_search_miss_includes_closest(svc):
    result = svc.search_journeys("dinosaurs quantum physics")
    assert result.get("closest") is not None


def test_search_empty_query_is_miss(svc):
    result = svc.search_journeys("")
    assert result.get("miss") is True


# ── get_random_journey ─────────────────────────────────────────────────────

def test_random_journey_returns_something(svc):
    j = svc.get_random_journey()
    assert j is not None


def test_random_journey_empty_store_returns_none(tmp_path):
    (tmp_path / "journeys.json").write_text("[]")
    repo = JsonRepository(str(tmp_path))
    repo.load()
    svc = Services(repo)
    assert svc.get_random_journey() is None


# ── content integrity: images and audio ───────────────────────────────────────

FULL_JOURNEYS = [
    "journey:it-started-with-a-choir",
    "journey:great-migration",
    "journey:on-her-own-terms",
]


def test_demo_journeys_all_songs_have_image(svc):
    """Every song in the three demo journeys must have album art."""
    for jid in FULL_JOURNEYS:
        j = svc.get_journey(jid)
        assert j is not None, f"{jid} not found"
        for song in j.songs:
            assert song.image_url, (
                f"{jid} song {song.position} '{song.title}' missing image_url"
            )


def test_demo_journeys_all_songs_have_preview(svc):
    """Every song in the three demo journeys must have a preview URL."""
    for jid in FULL_JOURNEYS:
        j = svc.get_journey(jid)
        for song in j.songs:
            assert song.preview_url, (
                f"{jid} song {song.position} '{song.title}' missing preview_url"
            )


def test_demo_journeys_all_songs_have_narration(svc):
    """Every song in the three demo journeys must have a blurb audio URL."""
    for jid in FULL_JOURNEYS:
        j = svc.get_journey(jid)
        for song in j.songs:
            assert song.blurb_audio_url, (
                f"{jid} song {song.position} '{song.title}' missing blurb_audio_url"
            )


def test_demo_journeys_have_intro_and_outro(svc):
    """Each demo journey must have intro and outro narration."""
    for jid in FULL_JOURNEYS:
        j = svc.get_journey(jid)
        assert j.intro_audio_url, f"{jid} missing intro_audio_url"
        assert j.outro_audio_url, f"{jid} missing outro_audio_url"


def test_all_journeys_have_at_least_one_song_image(svc):
    """Every journey (not just the three demo ones) needs a thumbnail for the homepage."""
    for j in svc.list_journeys():
        has_img = any(s.image_url for s in j.songs)
        assert has_img, f"{j.id} '{j.title}' has no song images — homepage card will be blank"
