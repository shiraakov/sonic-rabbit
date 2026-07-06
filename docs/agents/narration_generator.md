# NarrationGenerator

**Type:** Code (no LLM, no ADK LlmAgent)  
**Implementation:** `pipeline/tts.py`  
**API:** Gemini TTS REST (`gemini-2.5-flash-preview-tts`), same `GEMINI_API_KEY`

## Role

Converts all text content in a Journey to audio narration files and writes them to
`data/audio/{journey_id}/`. Populates `intro_audio_url`, `outro_audio_url`, and
`blurb_audio_url` on the Journey and Song objects.

This is deterministic code, not an LLM agent — TTS needs no reasoning. It runs
after JourneyResearcher, SongFetcher, and FactChecker have all completed, so the
text it narrates is the final verified version.

## What gets narrated

| Field | File | Content |
|-------|------|---------|
| `journey.blurb` | `intro.mp3` | Journey-level introduction |
| `song.blurb` (each) | `song_01.mp3` … `song_N.mp3` | Per-song contextual story |
| `journey.closing_paragraph` | `outro.mp3` | End-of-journey wrap-up |

## Output

Files written to `data/audio/{journey_id}/`:
```
intro.mp3
song_01.mp3
song_02.mp3
…
song_N.mp3
outro.mp3
```

The Journey object is mutated in place:
- `journey.intro_audio_url = "/audio/{journey_id}/intro.mp3"`
- `journey.outro_audio_url = "/audio/{journey_id}/outro.mp3"`
- `song.blurb_audio_url = "/audio/{journey_id}/song_NN.mp3"` for each song

## Audio format

- **API response:** `audio/L16` (raw 16-bit PCM, big-endian, 24 kHz, mono)
- **Stored as:** WAV (PCM → WAV header, no re-encoding required)
- **Voice:** fixed per run via `--voice` flag (default `Kore`); consistent across all
  clips in a journey so it sounds like one narrator

## Failure handling

Any single TTS call that fails (network error, API error, rate limit):
- Logs the error with the journey ID and segment name
- Sets the corresponding `*_audio_url` field to `null`
- Continues with remaining segments

A journey with some null audio URLs is valid and publishable. The UI degrades
gracefully to text-only for missing clips.

## Implementation sketch (`pipeline/tts.py`)

```python
async def generate_narration(journey: Journey, voice: str = "Kore") -> Journey:
    segments = [
        ("intro",  journey.blurb,              "intro"),
        ("outro",  journey.closing_paragraph,  "outro"),
    ] + [
        (f"song_{s.position:02d}", s.blurb, f"song_{s.position:02d}")
        for s in journey.songs
    ]
    audio_dir = Path(f"data/audio/{journey.id}")
    audio_dir.mkdir(parents=True, exist_ok=True)

    for label, text, filename in segments:
        try:
            wav_bytes = await call_gemini_tts(text, voice)
            (audio_dir / f"{filename}.mp3").write_bytes(wav_bytes)
            url = f"/audio/{journey.id}/{filename}.mp3"
            _set_url(journey, label, url)
        except Exception as e:
            log(f"TTS failed for {label}: {e}")
            _set_url(journey, label, None)
    return journey
```

Note: files are stored as WAV despite the `.mp3` extension in the URL path; this is
fine for browsers. If actual MP3 encoding is desired in M6+, add an ffmpeg step here.

## No trajectory eval needed

NarrationGenerator is pure code — no LLM decisions, no tool calls to assert. It is
covered by a unit test in `tests/test_tts.py` (M4) that mocks the Gemini REST call
and asserts correct file output and URL population.
