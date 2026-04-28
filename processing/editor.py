"""
Video editor – assembles the final short-form clip using MoviePy.

Responsibilities:
  - Trim the clip to the configured max duration.
  - Burn word-level subtitles as a visual overlay (fallback when Remotion
    is not available or for quick previews).
  - Normalize audio loudness to –14 LUFS (standard for social platforms).
  - Export as H.264 / AAC MP4 ready for Remotion or direct upload.
"""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from config.settings import settings

log = structlog.get_logger(__name__)

# Subtitle appearance
FONT_SIZE = 52
FONT_COLOR = "white"
STROKE_COLOR = "black"
STROKE_WIDTH = 2
WORDS_PER_LINE = 4
SUBTITLE_WRAP_WIDTH = 20  # characters per line for text wrapping


# ── Audio normalization ───────────────────────────────────────────────────────

def normalize_audio(input_path: Path, output_path: Path, target_lufs: float = -14.0) -> Path:
    """
    Two-pass FFmpeg loudnorm to reach *target_lufs* integrated loudness.
    """
    # Pass 1: measure
    measure_cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ]
    result = subprocess.run(measure_cmd, capture_output=True, text=True)
    # Extract JSON from stderr
    json_str = ""
    in_json = False
    for line in result.stderr.splitlines():
        if line.strip().startswith("{"):
            in_json = True
        if in_json:
            json_str += line
        if in_json and line.strip().endswith("}"):
            break

    try:
        stats = json.loads(json_str)
    except json.JSONDecodeError:
        log.warning("editor.loudnorm_parse_failed", stderr=result.stderr[:500])
        # Copy without normalization
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(input_path), "-c", "copy", str(output_path)],
            check=True,
        )
        return output_path

    loudnorm_filter = (
        f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:"
        f"measured_I={stats['input_i']}:"
        f"measured_LRA={stats['input_lra']}:"
        f"measured_TP={stats['input_tp']}:"
        f"measured_thresh={stats['input_thresh']}:"
        f"offset={stats['target_offset']}:linear=true:print_format=summary"
    )

    # Pass 2: apply
    apply_cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-af", loudnorm_filter,
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        str(output_path),
    ]
    result2 = subprocess.run(apply_cmd, capture_output=True, text=True)
    if result2.returncode != 0:
        log.error("editor.loudnorm_apply_failed", stderr=result2.stderr)
        raise RuntimeError("Audio normalization failed")

    return output_path


# ── Subtitle overlay (MoviePy) ────────────────────────────────────────────────

def _words_to_lines(
    words: List[Dict[str, Any]], words_per_line: int
) -> List[Dict[str, Any]]:
    """Group word-level timestamps into subtitle lines."""
    lines = []
    for i in range(0, len(words), words_per_line):
        chunk = words[i : i + words_per_line]
        if not chunk:
            continue
        text = " ".join(w["word"] for w in chunk)
        lines.append(
            {
                "text": text,
                "start": chunk[0]["start"],
                "end": chunk[-1]["end"],
            }
        )
    return lines


def burn_subtitles(
    video_path: Path,
    transcript: Dict[str, Any],
    output_path: Path,
) -> Path:
    """
    Burn word-grouped subtitles onto *video_path* using MoviePy TextClip.
    Returns *output_path*.
    """
    try:
        from moviepy.editor import (  # type: ignore
            VideoFileClip,
            TextClip,
            CompositeVideoClip,
        )
    except ImportError:
        log.warning("editor.moviepy_unavailable; skipping subtitle burn")
        return video_path

    words = transcript.get("words", [])
    if not words:
        log.warning("editor.no_words_in_transcript")
        return video_path

    lines = _words_to_lines(words, WORDS_PER_LINE)

    video = VideoFileClip(str(video_path))
    subtitle_clips = []

    for line in lines:
        start = max(0, line["start"])
        end = min(video.duration, line["end"])
        if end <= start:
            continue

        txt_clip = (
            TextClip(
                textwrap.fill(line["text"], SUBTITLE_WRAP_WIDTH),
                fontsize=FONT_SIZE,
                color=FONT_COLOR,
                stroke_color=STROKE_COLOR,
                stroke_width=STROKE_WIDTH,
                method="caption",
                size=(video.w - 80, None),
                align="center",
            )
            .set_position(("center", 0.75), relative=True)
            .set_start(start)
            .set_end(end)
        )
        subtitle_clips.append(txt_clip)

    if not subtitle_clips:
        return video_path

    final = CompositeVideoClip([video] + subtitle_clips)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    final.write_videofile(
        str(output_path),
        codec="libx264",
        audio_codec="aac",
        fps=video.fps,
        verbose=False,
        logger=None,
    )
    video.close()
    log.info("editor.subtitles_burned", output=str(output_path))
    return output_path


# ── Trim ─────────────────────────────────────────────────────────────────────

def trim_clip(
    input_path: Path,
    output_path: Path,
    max_duration: int | None = None,
) -> Path:
    """Trim the clip to *max_duration* seconds using FFmpeg (stream copy)."""
    duration = max_duration or settings.clip_max_duration
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-t", str(duration),
        "-c", "copy",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Trim failed: {result.stderr}")
    return output_path


# ── Full edit pipeline ────────────────────────────────────────────────────────

def edit_clip(
    raw_path: Path,
    transcript: Dict[str, Any],
    output_dir: Optional[Path] = None,
    add_subtitles: bool = True,
) -> Path:
    """
    Full edit pipeline:
      1. Trim to max duration.
      2. Normalize audio.
      3. Burn subtitles (if requested).

    Returns the final edited MP4 path.
    """
    out_dir = output_dir or settings.processed_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = raw_path.stem

    # Step 1: trim
    trimmed = out_dir / f"{stem}_trimmed.mp4"
    if not trimmed.exists():
        log.info("editor.trim", input=str(raw_path))
        trim_clip(raw_path, trimmed)

    # Step 2: normalize audio
    normalized = out_dir / f"{stem}_normalized.mp4"
    if not normalized.exists():
        log.info("editor.normalize", input=str(trimmed))
        normalize_audio(trimmed, normalized)

    if not add_subtitles or not transcript.get("words"):
        return normalized

    # Step 3: burn subtitles
    with_subs = out_dir / f"{stem}_subs.mp4"
    if not with_subs.exists():
        log.info("editor.subtitles", input=str(normalized))
        burn_subtitles(normalized, transcript, with_subs)

    return with_subs if with_subs.exists() else normalized
