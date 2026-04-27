"""
Python wrapper around the Remotion CLI renderer.

Renders the ClipTemplate composition with the provided props (video path,
transcript words, title, channel name) to a final branded MP4.

Requirements:
  - Node.js + npm must be installed on the host.
  - `npm install` must have been run inside the `remotion/` directory.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from config.settings import settings

log = structlog.get_logger(__name__)

REMOTION_DIR = Path(__file__).parent.parent / "remotion"


def render_clip(
    video_path: Path,
    transcript: Dict[str, Any],
    title: str,
    channel_name: str,
    output_dir: Optional[Path] = None,
    logo_src: Optional[str] = None,
) -> Path:
    """
    Render the Remotion ClipTemplate with the given props.

    Returns the path to the rendered MP4.
    """
    out_dir = output_dir or settings.renders_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{video_path.stem}_final.mp4"

    if out_path.exists():
        log.info("remotion_renderer.cache_hit", path=str(out_path))
        return out_path

    words: List[Dict[str, Any]] = transcript.get("words", [])
    duration_seconds: float = words[-1]["end"] if words else settings.clip_max_duration
    duration_frames = max(1, int(duration_seconds * 30) + 30)

    props: Dict[str, Any] = {
        "videoSrc": str(video_path.resolve()),
        "words": words,
        "title": title,
        "channelName": channel_name,
        "durationInFrames": duration_frames,
    }
    if logo_src:
        props["logoSrc"] = logo_src

    props_json = json.dumps(props)

    cmd = [
        "npx",
        "remotion",
        "render",
        "src/index.tsx",
        "ClipTemplate",
        str(out_path.resolve()),
        "--props",
        props_json,
    ]

    log.info("remotion_renderer.start", output=str(out_path))
    result = subprocess.run(
        cmd,
        cwd=str(REMOTION_DIR),
        capture_output=True,
        text=True,
        timeout=600,
    )

    if result.returncode != 0:
        log.error("remotion_renderer.error", stderr=result.stderr[-2000:])
        raise RuntimeError(f"Remotion render failed: {result.stderr[-500:]}")

    log.info("remotion_renderer.done", output=str(out_path))
    return out_path
