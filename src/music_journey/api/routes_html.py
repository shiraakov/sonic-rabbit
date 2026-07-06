"""HTML routes — Jinja2 + HTMX pages."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from ..core.services import Services
from ..pipeline.classifier import classify_request
from .deps import get_services

router = APIRouter()

templates = Jinja2Templates(
    directory=str(Path(__file__).parent.parent / "web" / "templates")
)


_CATEGORIES = [
    {"slug": "genre",              "label": "Genre",             "emoji": "🎵"},
    {"slug": "identity",           "label": "Identity",          "emoji": "✊"},
    {"slug": "geography",          "label": "Geography",         "emoji": "🌍"},
    {"slug": "instrument",         "label": "Instrument",        "emoji": "🎸"},
    {"slug": "society and culture","label": "Society & Culture", "emoji": "🏛️"},
]

@router.get("/")
def home(request: Request, q: str = "", cat: str = "", svc: Services = Depends(get_services)):
    all_journeys = svc.list_journeys()
    if q.strip():
        result = svc.search_journeys(q)
        if not result.get("miss"):
            return RedirectResponse(f"/j/{result['journey'].id}", status_code=302)
        return templates.TemplateResponse(
            request, "home.html",
            {
                "journeys": all_journeys,
                "chips": svc.get_chips(),
                "categories": _CATEGORIES,
                "active_cat": "",
                "q": q, "miss": True, "closest": result.get("closest"),
            },
        )
    journeys = (
        [j for j in all_journeys if cat in (j.categories or [])]
        if cat else all_journeys
    )
    return templates.TemplateResponse(
        request, "home.html",
        {"journeys": journeys, "chips": svc.get_chips(), "categories": _CATEGORIES, "active_cat": cat, "q": q},
    )


@router.post("/request")
async def submit_request(request: Request, svc: Services = Depends(get_services)):
    form = await request.form()
    title = str(form.get("title", "")).strip()[:100]
    description = str(form.get("description", "")).strip()[:300]

    def _render(status: str, message: str):
        return templates.TemplateResponse(
            request, "_request_result.html", {"status": status, "message": message}
        )

    if not title or not description:
        return _render("error", "Title and description are both required.")

    ip = request.client.host if request.client else "unknown"
    limiter = request.app.state.rate_limiter
    allowed, retry_after = limiter.check(ip)
    if not allowed:
        hours = max(1, retry_after // 3600)
        return _render("rate_limited", f"You've hit the limit (3 requests/day). Try again in {hours}h.")

    result = await classify_request(title, description, svc.list_journeys(), svc.embedder)
    if not result.valid:
        return _render("rejected", result.reason)

    limiter.record(ip)
    await request.app.state.queue.enqueue(
        title=title, description=description, theme=description, category=result.category
    )
    return _render("queued", "Got it — we'll add it to the library. Check back in a few hours.")


@router.get("/j/random")
def random_journey(svc: Services = Depends(get_services)):
    journey = svc.get_random_journey()
    if journey is None:
        return RedirectResponse("/", status_code=302)
    return RedirectResponse(f"/j/{journey.id}", status_code=302)


# /j/{id}/next and /j/{id}/step/{pos} must be before /j/{id} to avoid id=next/step
@router.get("/j/{id}/next")
def next_journey(id: str, svc: Services = Depends(get_services)):
    journey = svc.get_next_journey(id)
    if journey is None:
        return RedirectResponse("/", status_code=302)
    return RedirectResponse(f"/j/{journey.id}", status_code=302)


@router.get("/j/{id}/step/{pos}")
def song_step(request: Request, id: str, pos: int, svc: Services = Depends(get_services)):
    journey = svc.get_journey(id)
    if journey is None:
        raise HTTPException(status_code=404)
    song = svc.get_journey_step(id, pos)
    if song is None:
        raise HTTPException(status_code=404)
    total = len(journey.songs)
    return templates.TemplateResponse(
        request,
        "_song_step.html",
        {"song": song, "journey_id": id, "total": total},
    )


@router.get("/j/{id}/end")
def journey_end(request: Request, id: str, svc: Services = Depends(get_services)):
    journey = svc.get_journey(id)
    if journey is None:
        raise HTTPException(status_code=404)
    related = svc.get_related_journeys(id, limit=3)
    return templates.TemplateResponse(
        request,
        "journey_end.html",
        {"journey": journey, "related_journeys": related},
    )


@router.get("/j/{id}/playlist.txt")
def playlist_txt(id: str, svc: Services = Depends(get_services)):
    journey = svc.get_journey(id)
    if journey is None:
        raise HTTPException(status_code=404)
    songs = svc.get_playlist(id)
    lines = [f"{journey.title}\n{'─' * len(journey.title)}\n"]
    for song in songs:
        lines.append(f"{song.position}. {song.title} — {song.artist} ({song.month_year})")
        if song.streaming_links.spotify:
            lines.append(f"   Spotify: {song.streaming_links.spotify}")
        if song.streaming_links.apple_music:
            lines.append(f"   Apple Music: {song.streaming_links.apple_music}")
        if song.streaming_links.youtube:
            lines.append(f"   YouTube: {song.streaming_links.youtube}")
        lines.append("")
    return PlainTextResponse("\n".join(lines), headers={
        "Content-Disposition": f'attachment; filename="{id}.txt"'
    })


@router.get("/j/{id}/playlist.m3u")
def playlist_m3u(id: str, svc: Services = Depends(get_services)):
    journey = svc.get_journey(id)
    if journey is None:
        raise HTTPException(status_code=404)
    songs = svc.get_playlist(id)
    lines = ["#EXTM3U", f"#PLAYLIST:{journey.title}"]
    for song in songs:
        dur = -1
        lines.append(f"#EXTINF:{dur},{song.artist} - {song.title}")
        lines.append(song.preview_url or "")
    return PlainTextResponse("\n".join(lines), media_type="audio/x-mpegurl", headers={
        "Content-Disposition": f'attachment; filename="{id}.m3u"'
    })


@router.get("/j/{id}")
def journey_page(request: Request, id: str, svc: Services = Depends(get_services)):
    journey = svc.get_journey(id)
    if journey is None:
        raise HTTPException(status_code=404)
    songs = svc.get_playlist(id)
    total = len(songs)
    first_song = songs[0] if songs else None
    rest = songs[1:] if len(songs) > 1 else []
    return templates.TemplateResponse(
        request,
        "journey.html",
        {
            "journey": journey,
            "song": first_song,
            "rest_songs": rest,
            "total": total,
            "journey_id": id,
        },
    )
