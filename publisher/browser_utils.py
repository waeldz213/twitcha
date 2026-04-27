"""
Shared Playwright utilities for all publisher modules.

Features:
  - Rotating residential proxy support.
  - Randomised delays to simulate human behaviour.
  - Persistent cookie storage per account/platform.
  - Mobile user-agent rotation.
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from pathlib import Path
from typing import Optional

import structlog
from fake_useragent import UserAgent  # type: ignore
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from config.settings import settings

log = structlog.get_logger(__name__)

_ua = UserAgent(browsers=["chrome"], os="android")

# ── Delays ───────────────────────────────────────────────────────────────────

async def human_delay(min_sec: float = 1.0, max_sec: float = 4.0) -> None:
    """Sleep for a random duration to mimic human interaction timing."""
    await asyncio.sleep(random.uniform(min_sec, max_sec))


async def typing_delay() -> None:
    """Short pause between keystrokes."""
    await asyncio.sleep(random.uniform(0.05, 0.18))


async def human_type(page: Page, selector: str, text: str) -> None:
    """Type *text* character-by-character with randomised delays."""
    await page.click(selector)
    for char in text:
        await page.keyboard.type(char)
        await typing_delay()


# ── Proxy helpers ─────────────────────────────────────────────────────────────

def _pick_proxy() -> Optional[dict]:
    proxies = settings.proxy_list
    if not proxies:
        return None
    raw = random.choice(proxies)
    # Expected format: http://user:pass@host:port
    return {"server": raw}


# ── Cookie persistence ────────────────────────────────────────────────────────

def _cookie_path(platform: str, account: str) -> Path:
    p = settings.cookies_dir / platform
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{account}.json"


def _load_cookies(platform: str, account: str) -> Optional[list]:
    path = _cookie_path(platform, account)
    if path.exists():
        with path.open() as fh:
            return json.load(fh)
    return None


def _save_cookies(platform: str, account: str, cookies: list) -> None:
    path = _cookie_path(platform, account)
    with path.open("w") as fh:
        json.dump(cookies, fh)


# ── Context factory ───────────────────────────────────────────────────────────

async def build_context(
    playwright: Playwright,
    platform: str,
    account: str = "default",
) -> tuple[Browser, BrowserContext]:
    """
    Launch a Chromium browser with a mobile user-agent and optional proxy.
    Restores saved cookies if available.
    """
    proxy = _pick_proxy()
    user_agent = _ua.random

    browser = await playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
        ],
    )

    context_kwargs: dict = {
        "user_agent": user_agent,
        "viewport": {"width": 390, "height": 844},  # iPhone 14 Pro
        "device_scale_factor": 3,
        "is_mobile": True,
        "has_touch": True,
        "locale": "en-US",
        "timezone_id": "America/New_York",
    }
    if proxy:
        context_kwargs["proxy"] = proxy

    context = await browser.new_context(**context_kwargs)

    # Restore cookies
    cookies = _load_cookies(platform, account)
    if cookies:
        await context.add_cookies(cookies)
        log.info("publisher.cookies_restored", platform=platform, account=account)

    return browser, context


async def save_context_cookies(
    context: BrowserContext, platform: str, account: str = "default"
) -> None:
    cookies = await context.cookies()
    _save_cookies(platform, account, cookies)
    log.info("publisher.cookies_saved", platform=platform, account=account)
