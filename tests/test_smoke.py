"""Smoke tests — app boots, health check, audio serving."""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from music_journey.api.main import create_app

DATA_DIR = Path(__file__).parent.parent / "data"
AUDIO_DIR = DATA_DIR / "audio"


@pytest.fixture
def client(tmp_path):
    (tmp_path / "journeys.json").write_text("[]")
    app = create_app(data_dir=str(tmp_path))
    with TestClient(app) as c:
        yield c


@pytest.fixture
def real_client(tmp_path):
    shutil.copy(DATA_DIR / "journeys.json", tmp_path / "journeys.json")
    audio_dst = tmp_path / "audio"
    if AUDIO_DIR.exists():
        shutil.copytree(AUDIO_DIR, audio_dst)
    app = create_app(data_dir=str(tmp_path))
    with TestClient(app) as c:
        yield c


def test_health_empty_store(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["journeys"] == 0


# ── audio serving ─────────────────────────────────────────────────────────────

DEMO_JOURNEYS = [
    "journey:it-started-with-a-choir",
    "journey:great-migration",
    "journey:on-her-own-terms",
]


def test_demo_audio_files_exist_on_disk():
    """Every blurb_audio_url referenced in the demo journeys must exist on disk."""
    import json
    journeys = json.loads((DATA_DIR / "journeys.json").read_text())
    for j in journeys:
        if j["id"] not in DEMO_JOURNEYS:
            continue
        for field in ("intro_audio_url", "outro_audio_url"):
            url = j.get(field)
            if url:
                path = DATA_DIR / url.lstrip("/")
                assert path.exists(), f"{j['id']} {field} URL {url!r} has no file on disk"
        for song in j.get("songs", []):
            url = song.get("blurb_audio_url")
            if url:
                path = DATA_DIR / url.lstrip("/")
                assert path.exists(), (
                    f"{j['id']} song {song['position']} blurb_audio_url {url!r} "
                    "has no file on disk"
                )


def test_audio_endpoint_returns_200_with_no_cache(real_client):
    """Server must serve audio files and include Cache-Control: no-cache."""
    import json
    journeys = json.loads((DATA_DIR / "journeys.json").read_text())
    gospel = next(j for j in journeys if j["id"] == "journey:it-started-with-a-choir")
    url = gospel["songs"][0].get("blurb_audio_url")
    if not url:
        pytest.skip("no blurb_audio_url on gospel song 1")
    r = real_client.get(url)
    assert r.status_code == 200, f"audio {url} returned {r.status_code}"
    assert "no-cache" in r.headers.get("cache-control", ""), (
        f"audio response missing Cache-Control: no-cache (got: {r.headers.get('cache-control')})"
    )
