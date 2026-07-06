"""NarrationGenerator — TTS → audio files.

Backends:
  kokoro  (default) — Kokoro-82M ONNX local model; outputs WAV; requires HF_TOKEN on first run
  edge              — Microsoft Edge TTS via edge-tts; outputs MP3; no API key
  gemini            — Gemini TTS REST API; outputs WAV; requires GEMINI_API_KEY
  macos             — macOS `say` command; outputs WAV; no key needed; lower quality
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import struct
import subprocess
import types
import wave
from pathlib import Path
from typing import Literal, Optional

import httpx
import numpy as np

from ..core.models import Journey, Song

logger = logging.getLogger(__name__)

_TTS_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-tts-preview:generateContent"
_DEFAULT_VOICE_GEMINI = "Kore"
_DEFAULT_VOICE_MACOS = "Samantha"
_DEFAULT_VOICE_EDGE = "en-US-JennyNeural"
_DEFAULT_VOICE_KOKORO = "af_heart"
_SAMPLE_RATE = 24000
_CHANNELS = 1
_BITS_PER_SAMPLE = 16

_KOKORO_REPO = "onnx-community/Kokoro-82M-v1.0-ONNX-timestamped"
_KOKORO_VOICES = ["af_heart", "am_michael", "bf_emma", "af_bella", "am_adam"]
_KOKORO_VOICE_SHAPE = (510, 1, 256)
_KOKORO_VOICES_CACHE = Path.home() / ".cache" / "music_journey" / "kokoro_voices.npz"

TtsBackend = Literal["gemini", "macos", "edge", "kokoro"]

_BACKEND_EXT: dict[str, str] = {
    "gemini": "wav",
    "macos": "wav",
    "edge": "mp3",
    "kokoro": "wav",
}

# Module-level Kokoro instance — lazy-loaded on first TTS call
_kokoro_instance: Optional[object] = None


def _pcm_to_wav(raw_pcm: bytes) -> bytes:
    """Wrap raw LINEAR16 little-endian PCM bytes in a WAV header."""
    data_size = len(raw_pcm)
    byte_rate = _SAMPLE_RATE * _CHANNELS * _BITS_PER_SAMPLE // 8
    block_align = _CHANNELS * _BITS_PER_SAMPLE // 8
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_size, b"WAVE",
        b"fmt ", 16, 1, _CHANNELS, _SAMPLE_RATE, byte_rate, block_align, _BITS_PER_SAMPLE,
        b"data", data_size,
    )
    return header + raw_pcm


# ── Kokoro backend ───────────────────────────────────────────────────────────

def _get_kokoro() -> object:
    """Lazy-load the Kokoro instance. Downloads model on first call (~85MB, cached)."""
    global _kokoro_instance
    if _kokoro_instance is not None:
        return _kokoro_instance

    from huggingface_hub import hf_hub_download
    from kokoro_onnx import Kokoro, SAMPLE_RATE as KSR, MAX_PHONEME_LENGTH as KMPL

    logger.info("Kokoro: loading model (first run downloads ~85MB)...")
    model_path = hf_hub_download(_KOKORO_REPO, "onnx/model_quantized.onnx")

    if not _KOKORO_VOICES_CACHE.exists():
        logger.info("Kokoro: building voices cache (%d voices)...", len(_KOKORO_VOICES))
        _KOKORO_VOICES_CACHE.parent.mkdir(parents=True, exist_ok=True)
        voices = {}
        for name in _KOKORO_VOICES:
            raw = open(hf_hub_download(_KOKORO_REPO, f"voices/{name}.bin"), "rb").read()
            voices[name] = np.frombuffer(raw, dtype=np.float32).reshape(_KOKORO_VOICE_SHAPE)
        np.savez(str(_KOKORO_VOICES_CACHE), **voices)
        logger.info("Kokoro: voices cached at %s", _KOKORO_VOICES_CACHE)

    kokoro = Kokoro(model_path, str(_KOKORO_VOICES_CACHE))

    # Patch _create_audio: library bug passes speed as int32, model expects float32
    def _create_audio_fixed(self, phonemes, voice, speed):
        phonemes = phonemes[:KMPL]
        tokens = np.array(self.tokenizer.tokenize(phonemes), dtype=np.int64)
        voice_slice = voice[len(tokens)]
        inputs = {
            "input_ids": [[0, *tokens, 0]],
            "style": np.array(voice_slice, dtype=np.float32),
            "speed": np.array([speed], dtype=np.float32),
        }
        audio = self.sess.run(None, inputs)[0]
        # Flatten to 1D so Kokoro's internal np.concatenate works across chunks
        return audio.flatten(), KSR

    kokoro._create_audio = types.MethodType(_create_audio_fixed, kokoro)
    _kokoro_instance = kokoro
    logger.info("Kokoro: ready. Voices: %s", kokoro.get_voices())
    return kokoro


async def _kokoro_tts(text: str, voice: str, out_path: Path) -> bool:
    """Generate WAV via local Kokoro-82M ONNX model."""
    try:
        kokoro = await asyncio.get_event_loop().run_in_executor(None, _get_kokoro)
        samples, sr = await asyncio.get_event_loop().run_in_executor(
            None, lambda: kokoro.create(text, voice=voice, speed=1.0, lang="en-us")
        )
        audio = np.squeeze(samples)
        pcm = (audio * 32767).astype(np.int16)
        with wave.open(str(out_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm.tobytes())
        return True
    except Exception as e:
        logger.warning("TTS: Kokoro failed: %s", e)
        return False


# ── Edge TTS backend ──────────────────────────────────────────────────────────

async def _edge_tts(text: str, voice: str, out_path: Path) -> bool:
    """Generate MP3 via Microsoft Edge TTS. No API key required."""
    try:
        import edge_tts
        tts = edge_tts.Communicate(text, voice=voice)
        await tts.save(str(out_path))
        return True
    except Exception as e:
        logger.warning("TTS: edge-tts failed: %s", e)
        return False


# ── Gemini backend ────────────────────────────────────────────────────────────

async def _gemini_tts(text: str, voice: str, api_key: str, out_path: Path) -> bool:
    """Call Gemini TTS REST API and write a WAV file."""
    payload = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(_TTS_URL, params={"key": api_key}, json=payload)
            resp.raise_for_status()
            data = resp.json()
            inline = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("inlineData", {})
            )
            b64 = inline.get("data")
            if not b64:
                logger.warning("TTS: Gemini response contained no audio data")
                return False
            pcm = base64.b64decode(b64)
            out_path.write_bytes(_pcm_to_wav(pcm))
            return True
    except Exception as e:
        logger.warning("TTS: Gemini call failed: %s", e)
        return False


# ── macOS backend ─────────────────────────────────────────────────────────────

async def _macos_tts(text: str, voice: str, out_path: Path) -> bool:
    """Use macOS `say` command to write a WAV file."""
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                ["say", "-v", voice, "-o", str(out_path), "--data-format=LEI16@24000", text],
                capture_output=True,
            ),
        )
        if result.returncode != 0:
            logger.warning("TTS: macOS say failed: %s", result.stderr.decode())
            return False
        return True
    except Exception as e:
        logger.warning("TTS: macOS say error: %s", e)
        return False


# ── Main entry point ──────────────────────────────────────────────────────────

async def generate_narration(
    journey: Journey,
    audio_dir: Path,
    voice: str = _DEFAULT_VOICE_KOKORO,
    api_key: Optional[str] = None,
    backend: TtsBackend = "kokoro",
) -> Journey:
    """Generate TTS audio for a journey and return updated Journey with audio URLs.

    Writes files to audio_dir/{journey.id}/. Extension is .mp3 for edge, .wav otherwise.
    Skips files that already exist on disk. Failures are logged; TTS never aborts the pipeline.
    """
    ext = _BACKEND_EXT[backend]

    if backend == "gemini":
        key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not key:
            logger.warning("TTS: GEMINI_API_KEY not set — skipping TTS generation")
            return journey
        effective_voice = voice if voice != _DEFAULT_VOICE_KOKORO else _DEFAULT_VOICE_GEMINI
    elif backend == "macos":
        key = ""
        effective_voice = _DEFAULT_VOICE_MACOS
    elif backend == "kokoro":
        key = ""
        effective_voice = voice if voice != _DEFAULT_VOICE_EDGE else _DEFAULT_VOICE_KOKORO
    else:
        key = ""
        effective_voice = voice

    journey_audio_dir = audio_dir / journey.id
    journey_audio_dir.mkdir(parents=True, exist_ok=True)
    base_url = f"/audio/{journey.id}"

    async def _write(text: str, basename: str) -> Optional[str]:
        filename = f"{basename}.{ext}"
        path = journey_audio_dir / filename
        url = f"{base_url}/{filename}"
        if path.exists():
            logger.info("TTS: reusing existing %s", path)
            return url
        if backend == "gemini":
            ok = await _gemini_tts(text, effective_voice, key, path)
            await asyncio.sleep(2)
        elif backend == "macos":
            ok = await _macos_tts(text, effective_voice, path)
        elif backend == "kokoro":
            ok = await _kokoro_tts(text, effective_voice, path)
        else:
            ok = await _edge_tts(text, effective_voice, path)
        if ok:
            logger.info("TTS [%s]: wrote %s (%d bytes)", backend, path, path.stat().st_size)
            return url
        return None

    if journey.blurb:
        url = await _write(journey.blurb, "intro")
        if url:
            journey = journey.model_copy(update={"intro_audio_url": url})

    if journey.closing_paragraph:
        url = await _write(journey.closing_paragraph, "outro")
        if url:
            journey = journey.model_copy(update={"outro_audio_url": url})

    updated_songs = []
    for song in journey.songs:
        if song.blurb:
            url = await _write(song.blurb, f"song_{song.position:02d}")
            if url:
                song = song.model_copy(update={"blurb_audio_url": url})
        updated_songs.append(song)

    return journey.model_copy(update={"songs": updated_songs})
