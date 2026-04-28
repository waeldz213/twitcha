"""
Publisher dispatcher – routes a finished clip to all enabled platforms
with randomised delays between posts to avoid platform detection.
"""
from __future__ import annotations

import asyncio
import random
import time
from pathlib import Path
from typing import Any, Dict

import structlog

from config.settings import settings
from enrichment.ai_enricher import build_caption
from publisher.tiktok import upload_to_tiktok
from publisher.instagram import upload_to_instagram
from publisher.youtube import upload_to_youtube
from monitoring.metrics import (
    CLIPS_PUBLISHED,
    PUBLISH_ERRORS,
)

log = structlog.get_logger(__name__)

# Min / max delay (seconds) between platform posts
POST_DELAY_MIN = 60 * 20   # 20 min
POST_DELAY_MAX = 60 * 60   # 60 min


async def publish_all(
    video_path: Path,
    enriched: Dict[str, Any],
    account: str = "default",
) -> Dict[str, bool]:
    """
    Publish *video_path* to all enabled platforms sequentially with random delays.

    Returns a dict of {platform: success}.
    """
    caption = build_caption(enriched)
    title = enriched.get("title", "")
    description = enriched.get("description", "")
    hashtags = enriched.get("hashtags", [])

    results: Dict[str, bool] = {}

    platforms = []
    if settings.publish_tiktok:
        platforms.append("tiktok")
    if settings.publish_instagram:
        platforms.append("instagram")
    if settings.publish_youtube:
        platforms.append("youtube")

    random.shuffle(platforms)

    for idx, platform in enumerate(platforms):
        if idx > 0:
            delay = random.uniform(POST_DELAY_MIN, POST_DELAY_MAX)
            log.info("publisher.waiting_between_posts", platform=platform, delay_min=int(delay // 60))
            await asyncio.sleep(delay)

        log.info("publisher.posting", platform=platform, title=title)
        try:
            if platform == "tiktok":
                ok = await upload_to_tiktok(
                    video_path, caption=caption, account=account, hashtags=hashtags
                )
            elif platform == "instagram":
                ok = await upload_to_instagram(
                    video_path, caption=caption, account=account, hashtags=hashtags
                )
            elif platform == "youtube":
                ok = await upload_to_youtube(
                    video_path,
                    title=title,
                    description=description,
                    account=account,
                    hashtags=hashtags,
                )
            else:
                ok = False

            results[platform] = ok
            if ok:
                CLIPS_PUBLISHED.labels(platform=platform).inc()
                log.info("publisher.success", platform=platform)
            else:
                PUBLISH_ERRORS.labels(platform=platform).inc()
                log.warning("publisher.failed", platform=platform)

        except Exception:
            log.exception("publisher.exception", platform=platform)
            results[platform] = False
            PUBLISH_ERRORS.labels(platform=platform).inc()

    return results
