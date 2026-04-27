"""
YouTube Shorts publisher – uploads a short-form video via browser automation.

Navigates to YouTube Studio's upload flow and publishes as a Short
(vertical video ≤ 60 s is automatically classified as a Short).
"""
from __future__ import annotations

import asyncio
import random
from pathlib import Path
from typing import List, Optional

import structlog
from playwright.async_api import async_playwright

from publisher.browser_utils import (
    build_context,
    human_delay,
    save_context_cookies,
)

log = structlog.get_logger(__name__)

YOUTUBE_UPLOAD_URL = "https://studio.youtube.com"
YOUTUBE_TITLE_MAX_LENGTH = 100
YOUTUBE_DESCRIPTION_MAX_LENGTH = 500

# Hostname used to detect the Google login redirect
_GOOGLE_LOGIN_HOST = "accounts.google.com"


async def upload_to_youtube(
    video_path: Path,
    title: str,
    description: str,
    account: str = "default",
    hashtags: Optional[List[str]] = None,
    made_for_kids: bool = False,
) -> bool:
    """
    Upload *video_path* to YouTube Studio as a Short.

    Returns True on success, False on failure.
    """
    if not video_path.exists():
        log.error("youtube.video_not_found", path=str(video_path))
        return False

    full_description = description
    if hashtags:
        tags = " ".join(f"#{h}" for h in hashtags)
        full_description = f"{description}\n\n{tags}"

    async with async_playwright() as pw:
        browser, context = await build_context(pw, platform="youtube", account=account)
        try:
            page = await context.new_page()

            log.info("youtube.navigating")
            await page.goto(YOUTUBE_UPLOAD_URL, wait_until="networkidle", timeout=30_000)
            await human_delay(2, 4)

            # Detect Google login redirect by parsing the URL hostname
            from urllib.parse import urlparse
            parsed = urlparse(page.url)
            if parsed.hostname == _GOOGLE_LOGIN_HOST:
                log.error("youtube.not_logged_in", account=account)
                return False

            # Click "Create" then "Upload videos"
            create_btn_sel = 'button[aria-label="Create"], ytcp-button#create-icon'
            await page.wait_for_selector(create_btn_sel, timeout=20_000)
            await page.click(create_btn_sel)
            await human_delay(1, 2)

            await page.click('text="Upload videos"', timeout=10_000)
            await human_delay(1, 2)

            # Upload file
            log.info("youtube.uploading_file", path=str(video_path))
            async with page.expect_file_chooser() as fc_info:
                await page.click('button:has-text("SELECT FILES"), [aria-label="Select files to upload"]', timeout=10_000)
            file_chooser = await fc_info.value
            await file_chooser.set_files(str(video_path))
            await human_delay(3, 6)

            # Wait for upload dialog
            await page.wait_for_selector('ytcp-uploads-dialog', timeout=30_000)

            # Fill title
            title_sel = '#title-textarea div[contenteditable="true"]'
            await page.wait_for_selector(title_sel, timeout=20_000)
            await page.triple_click(title_sel)
            await page.keyboard.press("Control+a")
            for char in title[:YOUTUBE_TITLE_MAX_LENGTH]:
                await page.keyboard.type(char, delay=random.uniform(30, 80))
            await human_delay(0.5, 1.5)

            # Fill description
            desc_sel = '#description-textarea div[contenteditable="true"]'
            await page.click(desc_sel)
            for char in full_description[:YOUTUBE_DESCRIPTION_MAX_LENGTH]:
                await page.keyboard.type(char, delay=random.uniform(20, 60))
            await human_delay(0.5, 1.5)

            # Not made for kids
            kids_sel = (
                'tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]'
                if not made_for_kids
                else 'tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_MFK"]'
            )
            try:
                await page.click(kids_sel, timeout=10_000)
            except Exception:
                log.warning("youtube.kids_selector_not_found")

            # Next → Next → Next → Publish
            for _ in range(3):
                await human_delay(1, 2)
                next_btn = page.get_by_role("button", name="Next")
                await next_btn.click()

            await human_delay(1, 2)
            publish_btn = page.get_by_role("button", name="Publish")
            await publish_btn.wait_for(timeout=20_000)
            await publish_btn.click()
            await human_delay(3, 6)

            log.info("youtube.upload_success", account=account)
            await save_context_cookies(context, "youtube", account)
            return True

        except Exception:
            log.exception("youtube.upload_error", account=account)
            return False
        finally:
            await context.close()
            await browser.close()
