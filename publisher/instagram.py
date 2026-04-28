"""
Instagram Reels publisher – uploads a short-form video via browser automation.

Navigates to Instagram's web upload flow and publishes the clip as a Reel.
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

INSTAGRAM_URL = "https://www.instagram.com"


async def upload_to_instagram(
    video_path: Path,
    caption: str,
    account: str = "default",
    hashtags: Optional[List[str]] = None,
) -> bool:
    """
    Upload *video_path* to Instagram as a Reel.

    Returns True on success, False on failure.
    """
    if not video_path.exists():
        log.error("instagram.video_not_found", path=str(video_path))
        return False

    full_caption = caption
    if hashtags:
        tags = " ".join(f"#{h}" for h in hashtags)
        full_caption = f"{caption}\n.\n.\n.\n{tags}"

    async with async_playwright() as pw:
        browser, context = await build_context(pw, platform="instagram", account=account)
        try:
            page = await context.new_page()

            log.info("instagram.navigating")
            await page.goto(INSTAGRAM_URL, wait_until="networkidle", timeout=30_000)
            await human_delay(2, 4)

            if "accounts/login" in page.url:
                log.error("instagram.not_logged_in", account=account)
                return False

            # Click "Create" / "+" button
            create_btn_sel = 'svg[aria-label="New post"], [aria-label="Create"], a[href="/create/"]'
            await page.wait_for_selector(create_btn_sel, timeout=20_000)
            await page.click(create_btn_sel)
            await human_delay(1, 3)

            # Click "Reel" tab if present
            try:
                await page.click('text="Reel"', timeout=5_000)
                await human_delay(0.5, 1.5)
            except Exception:
                pass

            # Upload video
            log.info("instagram.uploading_file", path=str(video_path))
            async with page.expect_file_chooser() as fc_info:
                try:
                    await page.click('[aria-label="Add media"], button:has-text("Select from computer")', timeout=10_000)
                except Exception:
                    await page.click('input[type="file"]', timeout=10_000)
            file_chooser = await fc_info.value
            await file_chooser.set_files(str(video_path))
            await human_delay(3, 8)

            # Advance through steps (crop → filter → details)
            for step_label in ("Next", "Next", "Share"):
                try:
                    btn = page.get_by_role("button", name=step_label)
                    await btn.wait_for(timeout=30_000)
                    await human_delay(1, 2)
                    await btn.click()
                    await human_delay(1, 3)
                except Exception:
                    log.warning("instagram.step_btn_not_found", step=step_label)

            # Fill caption at the final step
            caption_sel = 'textarea[aria-label*="caption"], div[aria-label*="caption"], textarea[placeholder*="caption"]'
            try:
                await page.wait_for_selector(caption_sel, timeout=15_000)
                await page.click(caption_sel)
                for char in full_caption:
                    await page.keyboard.type(char, delay=random.uniform(25, 80))
                await human_delay(1, 2)
            except Exception:
                log.warning("instagram.caption_field_not_found")

            # Click Share / Post
            share_btn = page.get_by_role("button", name="Share")
            await share_btn.click()
            await human_delay(3, 6)

            log.info("instagram.upload_success", account=account)
            await save_context_cookies(context, "instagram", account)
            return True

        except Exception:
            log.exception("instagram.upload_error", account=account)
            return False
        finally:
            await context.close()
            await browser.close()
