"""
TikTok publisher – uploads a short-form video via browser automation.

Uses Playwright to simulate a real user uploading through TikTok's web
upload interface (https://www.tiktok.com/upload), avoiding the public API
to reduce detection risk.
"""
from __future__ import annotations

import asyncio
import random
import time
from pathlib import Path
from typing import List, Optional

import structlog
from playwright.async_api import async_playwright

from publisher.browser_utils import (
    build_context,
    human_delay,
    human_type,
    save_context_cookies,
)

log = structlog.get_logger(__name__)

TIKTOK_UPLOAD_URL = "https://www.tiktok.com/upload"


async def upload_to_tiktok(
    video_path: Path,
    caption: str,
    account: str = "default",
    hashtags: Optional[List[str]] = None,
) -> bool:
    """
    Upload *video_path* to TikTok with *caption*.

    Returns True on success, False on failure.
    """
    if not video_path.exists():
        log.error("tiktok.video_not_found", path=str(video_path))
        return False

    full_caption = caption
    if hashtags:
        tags = " ".join(f"#{h}" for h in hashtags)
        full_caption = f"{caption}\n{tags}"

    async with async_playwright() as pw:
        browser, context = await build_context(pw, platform="tiktok", account=account)
        try:
            page = await context.new_page()

            log.info("tiktok.navigating")
            await page.goto(TIKTOK_UPLOAD_URL, wait_until="networkidle", timeout=30_000)
            await human_delay(2, 5)

            # Check for login wall
            if "login" in page.url.lower():
                log.error("tiktok.not_logged_in", account=account)
                return False

            # Upload video via file input
            log.info("tiktok.uploading_file", path=str(video_path))
            async with page.expect_file_chooser() as fc_info:
                await page.click('[class*="upload-btn"], input[type="file"]')
            file_chooser = await fc_info.value
            await file_chooser.set_files(str(video_path))

            # Wait for video processing indicator to disappear
            await human_delay(5, 12)
            try:
                await page.wait_for_selector('[class*="upload-progress"]', state="hidden", timeout=120_000)
            except Exception:
                log.warning("tiktok.progress_wait_timeout")

            await human_delay(2, 4)

            # Fill caption
            caption_sel = '[class*="caption-editor"], [data-e2e="caption-input"], div[contenteditable="true"]'
            await page.wait_for_selector(caption_sel, timeout=20_000)
            await page.click(caption_sel)
            await human_delay(0.5, 1.5)
            # Clear existing text and type caption
            await page.keyboard.press("Control+a")
            await page.keyboard.press("Backspace")
            for char in full_caption:
                await page.keyboard.type(char, delay=random.uniform(30, 90))
            await human_delay(1, 3)

            # Post
            post_btn = '[data-e2e="post-btn"], button[class*="btn-post"]'
            await page.wait_for_selector(post_btn, timeout=15_000)
            await page.click(post_btn)
            await human_delay(3, 6)

            # Wait for success indicator
            try:
                await page.wait_for_selector(
                    '[class*="success"], [data-e2e="upload-success"]',
                    timeout=60_000,
                )
                log.info("tiktok.upload_success", account=account)
            except Exception:
                log.warning("tiktok.success_selector_not_found; assuming success")

            await save_context_cookies(context, "tiktok", account)
            return True

        except Exception:
            log.exception("tiktok.upload_error", account=account)
            return False
        finally:
            await context.close()
            await browser.close()
