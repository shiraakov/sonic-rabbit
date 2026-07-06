#!/usr/bin/env bash
# Regenerate gospel journey narration with Gemini TTS.
# Run this the day after Gemini quota resets (daily limit is 20 req/day on free tier).
set -e
cd "$(dirname "$0")/.."

JOURNEY_ID="journey:it-started-with-a-choir"
AUDIO_DIR="data/audio/${JOURNEY_ID}"

echo "==> Deleting existing WAV files..."
rm -rf "$AUDIO_DIR"

echo "==> Clearing audio URLs in journeys.json..."
python3 - <<'EOF'
import json, pathlib
p = pathlib.Path("data/journeys.json")
journeys = json.loads(p.read_text())
for j in journeys:
    if j["id"] == "journey:it-started-with-a-choir":
        j["intro_audio_url"] = None
        j["outro_audio_url"] = None
        for s in j.get("songs", []):
            s["blurb_audio_url"] = None
p.write_text(json.dumps(journeys, indent=2, ensure_ascii=False))
print("Cleared.")
EOF

echo "==> Running TTS with Gemini backend..."
uv run python scripts/recover_gospel.py --backend gemini

echo "==> Restarting web server..."
pkill -f "uvicorn music_journey" || true
sleep 1
uv run uvicorn music_journey.api.main:app --host 0.0.0.0 --port 8000 --app-dir src &
sleep 2

echo "==> Done. Open http://localhost:8000/j/journey:it-started-with-a-choir"
