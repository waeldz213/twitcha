"""
Video downloader using yt-dlp (Twitch / Kick VODs and clips).

Provides:
  - `download_clip(url, output_dir, filename_stem)` → Path
  - `download_live_segment(channel_url, duration_sec, output_dir)` → Path
      Uses streamlink for live segments around an engagement spike.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Optional

import yt_dlp  # type: ignore
import structlog

from config.settings import settings

log = structlog.get_logger(__name__)

# yt-dlp format: best mp4 ≤ 1080p
YDL_FORMAT = "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best"


def download_clip(
    url: str,
    output_dir: Optional[Path] = None,
    filename_stem: Optional[str] = None,
) -> Path:
    """
    Download a single clip from *url* using yt-dlp.

    Returns the path of the downloaded file.
    """
    out_dir = output_dir or settings.clips_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = filename_stem or f"clip_{int(time.time())}"
    output_template = str(out_dir / f"{stem}.%(ext)s")

    ydl_opts = {
        "format": YDL_FORMAT,
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "fragment_retries": 3,
    }

    log.info("downloader.start", url=url, output_dir=str(out_dir))

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # Determine the actual output filename
        if info:
            ext = info.get("ext", "mp4")
            out_path = out_dir / f"{stem}.{ext}"
            if out_path.exists():
                log.info("downloader.done", path=str(out_path))
                return out_path

    # Fallback: find any file with the expected stem
    candidates = sorted(out_dir.glob(f"{stem}.*"))
    if candidates:
        log.info("downloader.done", path=str(candidates[0]))
        return candidates[0]

    raise FileNotFoundError(f"yt-dlp did not produce a file for {url}")


def download_live_segment(
    channel_url: str,
    duration_sec: int = 60,
    output_dir: Optional[Path] = None,
) -> Path:
    """
    Capture *duration_sec* seconds from a live stream using streamlink.

    The segment starts from the current live position.
    Returns the path of the captured MP4 file.
    """
    out_dir = output_dir or settings.clips_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = f"live_{int(time.time())}"
    out_path = out_dir / f"{stem}.mp4"

    cmd = [
        "streamlink",
        "--output",
        str(out_path),
        "--hls-duration",
        str(duration_sec),
        channel_url,
        "best",
    ]

    log.info("downloader.live_start", channel_url=channel_url, duration=duration_sec)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration_sec + 60)

    if result.returncode != 0:
        log.error("downloader.live_error", stderr=result.stderr)
        raise RuntimeError(f"streamlink failed: {result.stderr}")

    if not out_path.exists():
        raise FileNotFoundError(f"streamlink did not produce {out_path}")

    log.info("downloader.live_done", path=str(out_path))
    return out_path


def build_twitch_live_url(channel: str) -> str:
    return f"https://www.twitch.tv/{channel}"


def build_kick_live_url(channel: str) -> str:
    return f"https://kick.com/{channel}"
