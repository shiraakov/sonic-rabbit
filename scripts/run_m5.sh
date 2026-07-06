#!/bin/bash
# M5 journey seeding — two-phase approval flow.
#
# Phase 1 (--draft-only): generates text, prints it, saves to data/drafts/.
# Phase 2 (full run):     reads saved draft, runs fetcher + fact-check + TTS + publish.
#
# Usage:
#   bash scripts/run_m5.sh draft    # phase 1: generate and review all drafts
#   bash scripts/run_m5.sh publish  # phase 2: publish approved drafts
#   bash scripts/run_m5.sh all      # phase 1 + phase 2 back-to-back (no review gap)

set -e
cd "$(git rev-parse --show-toplevel)"

PHASE="${1:-all}"

draft_journey() {
  local label="$1"
  local title="$2"
  local subtitle="$3"
  local theme="$4"
  echo ""
  echo "=========================================="
  echo "DRAFT: $title"
  echo "=========================================="
  uv run python -m music_journey.pipeline.run \
    --theme "$theme" \
    --title "$title" \
    --subtitle "$subtitle" \
    --draft-only \
    --data-dir data \
    2>/dev/null
}

publish_journey() {
  local label="$1"
  local title="$2"
  local subtitle="$3"
  local theme="$4"
  local logfile="/tmp/run_${label}.log"
  echo ""
  echo "=========================================="
  echo "PUBLISHING: $title"
  echo "=========================================="
  uv run python -m music_journey.pipeline.run \
    --theme "$theme" \
    --title "$title" \
    --subtitle "$subtitle" \
    --data-dir data \
    2> "$logfile"
  echo "=== DONE: $label ==="
}

run_all() {
  local fn="$1"; shift
  $fn "on-her-own-terms" \
    "Turns Out Women Had Opinions" \
    "Pop anthems that weren't asking permission" \
    "On Her Own Terms: feminist pop anthems from the 1960s to today"

  $fn "children" \
    "Adorable Songs With an Agenda" \
    "What kids' music worldwide is actually teaching" \
    "What We Teach Our Children: children's songs from around the world and the values they quietly pass down"

  $fn "jazz" \
    "Nobody Planned This" \
    "New Orleans accidentally invented everything" \
    "Before It Had a Name: the musicians and moments that invented jazz — improvisation, rhythm, and swing"

  $fn "guitar" \
    "Lyrics Optional" \
    "Six centuries of guitar doing all the talking" \
    "The Talking Guitar: instrumental guitar pieces through the centuries and how the guitar's own evolution changed what players could say with it"

  $fn "travel" \
    "Getting Out of Here" \
    "The music of going somewhere" \
    "Always Moving: from frontier folk songs heading west to the great American road trip soundtrack"

  $fn "gospel" \
    "It Started With a Choir" \
    "How gospel built soul, R&B, and funk" \
    "Raise Every Voice: how gospel music built community and became the root of soul, R&B, and funk"

  $fn "bristol" \
    "Beautiful Music for Ugly Times" \
    "What Portishead had to say about Thatcher's England" \
    "Grey Skies and Drum Machines: how Bristol artists turned Thatcher's England into trip hop"
}

case "$PHASE" in
  draft)
    echo "=== PHASE 1: generating drafts ==="
    run_all draft_journey
    echo ""
    echo "Drafts saved to data/drafts/. Review them, then run:"
    echo "  bash scripts/run_m5.sh publish"
    ;;
  publish)
    echo "=== PHASE 2: publishing journeys ==="
    run_all publish_journey
    echo ""
    echo "=========================================="
    echo "ALL JOURNEYS PUBLISHED"
    echo "=========================================="
    ;;
  all)
    echo "=== PHASE 1: generating drafts ==="
    run_all draft_journey
    echo ""
    echo "=== PHASE 2: publishing ==="
    run_all publish_journey
    echo ""
    echo "=========================================="
    echo "ALL DONE"
    echo "=========================================="
    ;;
  *)
    echo "Usage: bash scripts/run_m5.sh [draft|publish|all]"
    exit 1
    ;;
esac
