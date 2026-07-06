"""FastAPI dependency injectors."""

from __future__ import annotations

from fastapi import Request

from ..core.services import Services


def get_services(request: Request) -> Services:
    return request.app.state.services
