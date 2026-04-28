"""
Audio/video transcription using OpenAI Whisper (local) or AssemblyAI (SaaS).

Output format:
  {
    "text": "full transcript",
    "language": "en",
    "words": [
      {"word": "Hello", "start": 0.0, "end": 0.4, "confidence": 0.99},
      ...
    ],
    "segments": [
      {"id": 0, "start": 0.0, "end": 3.5, "text": "Hello world"},
      ...
    ]
  }
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import structlog

from config.settings import settings

log = structlog.get_logger(__name__)


# ── Local Whisper ────────────────────────────────────────────────────────────

def _transcribe_whisper(video_path: Path) -> Dict[str, Any]:
    """Transcribe using local Whisper model (free, runs on CPU/GPU)."""
    import whisper  # type: ignore

    log.info("transcriber.whisper.start", model=settings.whisper_model, path=str(video_path))
    model = whisper.load_model(settings.whisper_model, device=settings.whisper_device)
    result = model.transcribe(
        str(video_path),
        word_timestamps=True,
        verbose=False,
    )

    words: List[Dict[str, Any]] = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            words.append(
                {
                    "word": w["word"].strip(),
                    "start": round(w["start"], 3),
                    "end": round(w["end"], 3),
                    "confidence": round(w.get("probability", 1.0), 4),
                }
            )

    transcript: Dict[str, Any] = {
        "text": result["text"].strip(),
        "language": result.get("language", "unknown"),
        "words": words,
        "segments": [
            {
                "id": s["id"],
                "start": round(s["start"], 3),
                "end": round(s["end"], 3),
                "text": s["text"].strip(),
            }
            for s in result.get("segments", [])
        ],
    }
    log.info("transcriber.whisper.done", word_count=len(words))
    return transcript


# ── AssemblyAI ───────────────────────────────────────────────────────────────

def _transcribe_assemblyai(video_path: Path) -> Dict[str, Any]:
    """Transcribe using AssemblyAI cloud API (faster, paid)."""
    import assemblyai as aai  # type: ignore

    log.info("transcriber.assemblyai.start", path=str(video_path))
    aai.settings.api_key = settings.assemblyai_api_key

    config = aai.TranscriptionConfig(
        speech_model=aai.SpeechModel.best,
        word_boost=[],
        punctuate=True,
        format_text=True,
        language_detection=True,
    )
    transcriber = aai.Transcriber(config=config)
    transcript_obj = transcriber.transcribe(str(video_path))

    if transcript_obj.status == aai.TranscriptStatus.error:
        raise RuntimeError(f"AssemblyAI error: {transcript_obj.error}")

    words: List[Dict[str, Any]] = [
        {
            "word": w.text,
            "start": round((w.start or 0) / 1000, 3),
            "end": round((w.end or 0) / 1000, 3),
            "confidence": round(w.confidence or 1.0, 4),
        }
        for w in (transcript_obj.words or [])
    ]

    segments: List[Dict[str, Any]] = []
    if transcript_obj.utterances:
        for idx, utt in enumerate(transcript_obj.utterances):
            segments.append(
                {
                    "id": idx,
                    "start": round((utt.start or 0) / 1000, 3),
                    "end": round((utt.end or 0) / 1000, 3),
                    "text": utt.text,
                }
            )

    result: Dict[str, Any] = {
        "text": transcript_obj.text or "",
        "language": transcript_obj.language_code or "unknown",
        "words": words,
        "segments": segments,
    }
    log.info("transcriber.assemblyai.done", word_count=len(words))
    return result


# ── Public API ───────────────────────────────────────────────────────────────

def transcribe(video_path: Path, output_dir: Path | None = None) -> Dict[str, Any]:
    """
    Transcribe *video_path* and return a word-timestamped JSON object.

    Saves the JSON alongside the video (or in *output_dir*) for caching.
    Re-uses cached JSON if it already exists.
    """
    out_dir = output_dir or video_path.parent
    cache_path = out_dir / (video_path.stem + "_transcript.json")

    if cache_path.exists():
        log.info("transcriber.cache_hit", path=str(cache_path))
        with cache_path.open() as fh:
            return json.load(fh)

    if settings.use_assemblyai and settings.assemblyai_api_key:
        transcript = _transcribe_assemblyai(video_path)
    else:
        transcript = _transcribe_whisper(video_path)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("w") as fh:
        json.dump(transcript, fh, ensure_ascii=False, indent=2)

    log.info("transcriber.saved", path=str(cache_path))
    return transcript
