"""
Celery tasks – the full clip processing pipeline.

Pipeline steps (each step is idempotent via file-existence checks):
  1. Download the clip.
  2. Smart-crop to 9:16.
  3. Transcribe (Whisper / AssemblyAI).
  4. Edit (trim + audio normalization + subtitle burn).
  5. Remotion render (styled subtitles + branding).
  6. AI enrichment (title, description, hashtags).
  7. Publish to enabled platforms.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Dict, Optional

import structlog
from celery import Task  # type: ignore

from orchestration.celery_app import app
from monitoring.metrics import (
    CLIPS_DOWNLOADED,
    CLIPS_PROCESSED,
    PIPELINE_ERRORS,
    PIPELINE_DURATION,
)

log = structlog.get_logger(__name__)


# ── Helper ────────────────────────────────────────────────────────────────────

def _run_async(coro) -> Any:
    """Run an async coroutine from a synchronous Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Main pipeline task ────────────────────────────────────────────────────────

@app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name="orchestration.tasks.process_clip_pipeline",
)
def process_clip_pipeline(
    self: Task,
    source: str,
    channel: str,
    triggered_at: float,
    clip_id: Optional[str] = None,
    clip_url: Optional[str] = None,
    clip_thumbnail: Optional[str] = None,
) -> Dict[str, Any]:
    """
    End-to-end pipeline: download → crop → transcribe → edit → render → publish.
    """
    start = time.time()
    log.info(
        "pipeline.start",
        source=source,
        channel=channel,
        clip_id=clip_id,
        clip_url=clip_url,
    )

    try:
        result = _run_pipeline(
            source=source,
            channel=channel,
            clip_id=clip_id,
            clip_url=clip_url,
        )
        elapsed = time.time() - start
        PIPELINE_DURATION.observe(elapsed)
        CLIPS_PROCESSED.inc()
        log.info("pipeline.done", elapsed=round(elapsed, 1), result=result)
        return result

    except Exception as exc:
        PIPELINE_ERRORS.inc()
        log.exception("pipeline.error", source=source, channel=channel)
        raise self.retry(exc=exc)


def _pipeline_clip_url(source: str, channel: str, clip_url: Optional[str]) -> str:
    """Resolve or build the URL to download."""
    if clip_url:
        return clip_url
    from ingestion.downloader import build_twitch_live_url, build_kick_live_url
    if source == "kick":
        return build_kick_live_url(channel)
    return build_twitch_live_url(channel)


def _run_pipeline(
    source: str,
    channel: str,
    clip_id: Optional[str],
    clip_url: Optional[str],
) -> Dict[str, Any]:
    from config.settings import settings
    from ingestion.downloader import download_clip, download_live_segment
    from processing.smart_crop import smart_crop
    from processing.transcriber import transcribe
    from processing.editor import edit_clip
    from processing.remotion_renderer import render_clip
    from enrichment.ai_enricher import enrich_clip

    stem = clip_id or f"{source}_{channel}_{int(time.time())}"

    # ── Step 1: Download ──────────────────────────────────────────────────────
    url = _pipeline_clip_url(source, channel, clip_url)
    log.info("pipeline.step1_download", url=url)
    if source in ("twitch", "twitch_api") and clip_url:
        raw_path = download_clip(url, filename_stem=stem)
    else:
        raw_path = download_live_segment(url, duration_sec=settings.clip_max_duration)
    CLIPS_DOWNLOADED.inc()

    # ── Step 2: Smart crop ────────────────────────────────────────────────────
    log.info("pipeline.step2_crop")
    cropped_path = smart_crop(raw_path, output_stem=stem + "_vertical")

    # ── Step 3: Transcribe ────────────────────────────────────────────────────
    log.info("pipeline.step3_transcribe")
    transcript = transcribe(cropped_path, output_dir=settings.processed_dir)

    # ── Step 4: Edit ──────────────────────────────────────────────────────────
    log.info("pipeline.step4_edit")
    edited_path = edit_clip(
        cropped_path,
        transcript,
        output_dir=settings.processed_dir,
        add_subtitles=False,  # subtitles will be handled by Remotion
    )

    # ── Step 5: AI enrichment ─────────────────────────────────────────────────
    log.info("pipeline.step5_enrich")
    enriched = enrich_clip(
        transcript_text=transcript.get("text", ""),
        channel_name=channel,
        platform="TikTok",
    )

    # ── Step 6: Remotion render ───────────────────────────────────────────────
    log.info("pipeline.step6_render")
    try:
        final_path = render_clip(
            video_path=edited_path,
            transcript=transcript,
            title=enriched["title"],
            channel_name=f"@{channel}",
            output_dir=settings.renders_dir,
        )
    except Exception:
        log.warning("pipeline.remotion_unavailable; using edited path")
        final_path = edited_path

    # ── Step 7: Publish ───────────────────────────────────────────────────────
    log.info("pipeline.step7_publish")
    from publisher.dispatcher import publish_all
    publish_results = _run_async(publish_all(final_path, enriched))

    return {
        "clip_id": stem,
        "final_path": str(final_path),
        "enriched": enriched,
        "publish_results": publish_results,
    }


# ── Periodic task: poll Twitch clips ─────────────────────────────────────────

@app.task(name="orchestration.tasks.poll_twitch_clips")
def poll_twitch_clips() -> None:
    """Celery Beat task: poll Twitch API for new clips every 2 minutes."""
    from ingestion.clip_fetcher import TwitchClipFetcher

    fetcher = TwitchClipFetcher()
    _run_async(fetcher._poll_all_channels())
    log.info("poll_twitch_clips.done")
