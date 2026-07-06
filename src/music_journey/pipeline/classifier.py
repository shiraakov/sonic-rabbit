"""Journey request classifier.

Step 1: Semantic duplicate check via MiniLM embedder (if available). Score >= 0.65 = too similar.
Step 2: Single Gemini flash call for spam/prank detection + category assignment.

Fails open — if the Gemini call errors, the request is auto-accepted to avoid blocking users.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from ..core.models import Journey
    from ..discovery.embedder import JourneyEmbedder

logger = logging.getLogger(__name__)

_DUPLICATE_THRESHOLD = 0.65
_VALID_CATEGORIES = {"genre", "identity", "geography", "instrument", "society and culture"}

_PROMPT = """\
You are a classifier for Sonic Rabbit, a curated music-history podcast app.

Existing journeys (title | theme):
{existing}

New request:
Title: {title}
Description: {description}

Rules:
- Reject: spam, offensive content, gibberish, requests too vague to build a 6-song curated journey.
- Accept: any specific music-history angle, even niche ones.
- Do NOT reject something just because it sounds unusual — music history is full of surprises.

Assign the single best category: genre, identity, geography, instrument, society and culture

Respond with JSON only, no markdown:
{{"valid": true or false, "reason": "one concise sentence", "category": "best category name or empty string if invalid"}}"""


@dataclass
class ClassifierResult:
    valid: bool
    reason: str
    category: str = ""
    duplicate_of: Optional[str] = None


async def classify_request(
    title: str,
    description: str,
    existing_journeys: "List[Journey]",
    embedder: "Optional[JourneyEmbedder]",
) -> ClassifierResult:
    # Step 1: semantic duplicate check
    if embedder is not None:
        result = embedder.search(f"{title} {description}")
        if not result.get("miss") and result.get("score", 0.0) >= _DUPLICATE_THRESHOLD:
            closest = result["journey"]
            return ClassifierResult(
                valid=False,
                reason=f'Too similar to an existing journey: "{closest.title}"',
                duplicate_of=closest.id,
            )

    # Step 2: Gemini classifier
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        logger.warning("Classifier: GEMINI_API_KEY not set — auto-accepting")
        return ClassifierResult(valid=True, reason="Auto-accepted (no classifier key)", category="")

    existing = "\n".join(f"- {j.title} | {j.theme}" for j in existing_journeys) or "(none yet)"
    prompt = _PROMPT.format(existing=existing, title=title, description=description)

    try:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
                params={"key": api_key},
                json={"contents": [{"parts": [{"text": prompt}]}]},
            )
            resp.raise_for_status()
            raw = (
                resp.json()
                .get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "{}")
            )
        # Strip markdown fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw)
        parsed = json.loads(raw)
        category = parsed.get("category", "").lower().strip()
        if category not in _VALID_CATEGORIES:
            category = ""
        return ClassifierResult(
            valid=bool(parsed.get("valid", False)),
            reason=parsed.get("reason", ""),
            category=category,
        )
    except Exception as e:
        logger.warning("Classifier: failed (%s) — auto-accepting", e)
        return ClassifierResult(valid=True, reason=f"Classifier unavailable: {e}", category="")
