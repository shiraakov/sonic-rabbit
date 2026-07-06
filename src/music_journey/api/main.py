"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ..core.config import settings
from ..core.repository_json import JsonRepository
from ..core.services import Services
from ..discovery.demand_log import DemandLog
from ..pipeline.queue_manager import QueueManager, queue_worker
from .rate_limiter import RateLimiter
from .routes_html import router as html_router
from .routes_json import router as json_router

logger = logging.getLogger(__name__)


def _try_build_embedder(journeys):
    try:
        from ..discovery.embedder import JourneyEmbedder
        embedder = JourneyEmbedder()
        embedder.index(journeys)
        logger.info("Semantic embedder ready (%d journeys indexed)", len(journeys))
        return embedder
    except ImportError:
        logger.info(
            "sentence-transformers not installed — semantic search disabled "
            "(install with: uv sync --extra discovery)"
        )
        return None


def create_app(data_dir: str | None = None) -> FastAPI:
    resolved = Path(data_dir or settings.data_dir)

    repo = JsonRepository(str(resolved))
    repo.load()
    journeys = repo.all_journeys()
    embedder = _try_build_embedder(journeys)
    demand_log = DemandLog(resolved)
    queue_mgr = QueueManager(resolved)
    rate_limiter = RateLimiter()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        worker = asyncio.create_task(queue_worker(queue_mgr, resolved, repo, embedder))
        yield
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass

    app = FastAPI(title="Music Journey", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.state.repo = repo
    app.state.services = Services(repo, embedder=embedder, demand_log=demand_log)
    app.state.data_dir = resolved
    app.state.queue = queue_mgr
    app.state.rate_limiter = rate_limiter

    app.include_router(json_router)
    app.include_router(html_router)

    static_dir = Path(__file__).parent.parent / "web" / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    audio_dir = resolved / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # Serve audio with no-cache so browsers always re-validate against ETag/Last-Modified
    from fastapi.responses import FileResponse
    from fastapi import Path as FPath

    @app.get("/audio/{path:path}")
    async def serve_audio(path: str = FPath(...)):
        full = audio_dir / path
        if not full.exists():
            from fastapi import HTTPException
            raise HTTPException(status_code=404)
        return FileResponse(
            str(full),
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "journeys": len(app.state.repo.all_journeys()),
        }

    return app


app = create_app()
