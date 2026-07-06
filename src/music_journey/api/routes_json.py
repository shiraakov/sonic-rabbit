"""JSON API routes — /api/*"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..core.models import Journey, Song
from ..core.services import Services
from ..pipeline.classifier import classify_request
from .deps import get_services

router = APIRouter(prefix="/api")


@router.get("/chips")
def chips(svc: Services = Depends(get_services)) -> list[dict]:
    return svc.get_chips()


@router.get("/journeys")
def list_journeys(svc: Services = Depends(get_services)) -> list[Journey]:
    return svc.list_journeys()


# /journeys/next must be registered before /journeys/{id}
@router.get("/journeys/next")
def next_journey(from_id: str = "", svc: Services = Depends(get_services)) -> Journey:
    journey = svc.get_next_journey(from_id) if from_id else svc.get_random_journey()
    if journey is None:
        raise HTTPException(status_code=404, detail="No journeys available")
    return journey


@router.get("/journeys/{id}")
def get_journey(id: str, svc: Services = Depends(get_services)) -> Journey:
    journey = svc.get_journey(id)
    if journey is None:
        raise HTTPException(status_code=404, detail="Journey not found")
    return journey


@router.get("/journeys/{id}/related")
def related_journeys(id: str, limit: int = 3, svc: Services = Depends(get_services)) -> list[Journey]:
    return svc.get_related_journeys(id, limit=limit)


@router.get("/journeys/{id}/songs/{pos}")
def get_song(id: str, pos: int, svc: Services = Depends(get_services)) -> Song:
    song = svc.get_journey_step(id, pos)
    if song is None:
        raise HTTPException(status_code=404, detail="Song not found")
    return song


class JourneyRequestIn(BaseModel):
    title: str = Field(..., max_length=100)
    description: str = Field(..., max_length=300)


@router.post("/request-journey")
async def request_journey(
    request: Request,
    body: JourneyRequestIn,
    svc: Services = Depends(get_services),
) -> dict:
    ip = request.client.host if request.client else "unknown"
    limiter = request.app.state.rate_limiter
    allowed, retry_after = limiter.check(ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {max(1, retry_after // 3600)}h.",
            headers={"Retry-After": str(retry_after)},
        )
    result = await classify_request(body.title, body.description, svc.list_journeys(), svc.embedder)
    if not result.valid:
        raise HTTPException(status_code=422, detail=result.reason)
    limiter.record(ip)
    await request.app.state.queue.enqueue(
        title=body.title, description=body.description, theme=body.description, category=result.category
    )
    return {"status": "queued", "message": "Your journey has been queued. Check back in a few hours."}


@router.get("/search")
def search(q: str = "", svc: Services = Depends(get_services)) -> dict:
    if not q.strip():
        return {"miss": True, "closest": None}
    result = svc.search_journeys(q)
    if result.get("miss"):
        closest = result.get("closest")
        return {"miss": True, "closest": closest.model_dump() if closest else None}
    journey = result["journey"]
    return {"miss": False, "journey": journey.model_dump(), "score": result["score"]}
