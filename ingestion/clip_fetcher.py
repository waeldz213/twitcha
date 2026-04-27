"""
Twitch Helix API – fetches auto-generated clips for monitored channels.

Used as a supplementary ingestion source: polls the clips endpoint on a
configurable interval, deduplicates already-processed clips, and enqueues
new ones that meet the quality threshold (view_count / duration).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

import httpx
import structlog

from config.settings import settings
from orchestration.tasks import process_clip_pipeline

log = structlog.get_logger(__name__)

HELIX_BASE = "https://api.twitch.tv/helix"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
POLL_INTERVAL_SECONDS = 120  # seconds between Twitch API clip polls
MIN_VIEW_COUNT = 5  # ignore low-quality clips


class TwitchClipFetcher:
    """
    Periodically polls Twitch Helix /clips for each configured channel,
    filters by freshness and view count, then enqueues new clips.
    """

    def __init__(self) -> None:
        self._access_token: Optional[str] = None
        self._token_expiry: float = 0.0
        self._seen_clip_ids: set[str] = set()

    # ── Auth ────────────────────────────────────────────────────────────────

    async def _get_access_token(self) -> str:
        if self._access_token and time.time() < self._token_expiry - 60:
            return self._access_token

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                TOKEN_URL,
                params={
                    "client_id": settings.twitch_client_id,
                    "client_secret": settings.twitch_client_secret,
                    "grant_type": "client_credentials",
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            self._access_token = data["access_token"]
            self._token_expiry = time.time() + data["expires_in"]
            log.info("twitch.token_refreshed")
            return self._access_token

    def _auth_headers(self, token: str) -> Dict[str, str]:
        return {
            "Client-ID": settings.twitch_client_id,
            "Authorization": f"Bearer {token}",
        }

    # ── Broadcaster ID lookup ────────────────────────────────────────────────

    async def _get_broadcaster_id(
        self, client: httpx.AsyncClient, token: str, login: str
    ) -> Optional[str]:
        resp = await client.get(
            f"{HELIX_BASE}/users",
            params={"login": login},
            headers=self._auth_headers(token),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return data[0]["id"] if data else None

    # ── Clip fetching ────────────────────────────────────────────────────────

    async def _fetch_clips(
        self,
        client: httpx.AsyncClient,
        token: str,
        broadcaster_id: str,
        started_at: str,
    ) -> List[Dict[str, Any]]:
        """Return clips created after *started_at* (RFC 3339)."""
        params = {
            "broadcaster_id": broadcaster_id,
            "started_at": started_at,
            "first": 20,
        }
        resp = await client.get(
            f"{HELIX_BASE}/clips",
            params=params,
            headers=self._auth_headers(token),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("data", [])

    # ── Main loop ────────────────────────────────────────────────────────────

    async def run(self) -> None:
        log.info("clip_fetcher.started", channels=settings.twitch_channels)
        while True:
            try:
                await self._poll_all_channels()
            except Exception:
                log.exception("clip_fetcher.poll_error")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _poll_all_channels(self) -> None:
        from datetime import datetime, timezone, timedelta

        token = await self._get_access_token()
        # Look back a 5-minute window
        started_at = (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        async with httpx.AsyncClient() as client:
            for channel in settings.twitch_channels:
                try:
                    broadcaster_id = await self._get_broadcaster_id(
                        client, token, channel
                    )
                    if not broadcaster_id:
                        log.warning("clip_fetcher.channel_not_found", channel=channel)
                        continue

                    clips = await self._fetch_clips(
                        client, token, broadcaster_id, started_at
                    )
                    for clip in clips:
                        await self._handle_clip(clip, channel)
                except Exception:
                    log.exception("clip_fetcher.channel_error", channel=channel)

    async def _handle_clip(self, clip: Dict[str, Any], channel: str) -> None:
        clip_id: str = clip["id"]
        if clip_id in self._seen_clip_ids:
            return
        if clip.get("view_count", 0) < MIN_VIEW_COUNT:
            return

        duration: float = clip.get("duration", 0)
        if not (settings.clip_min_duration <= duration <= settings.clip_max_duration):
            return

        self._seen_clip_ids.add(clip_id)
        log.info(
            "clip_fetcher.new_clip",
            clip_id=clip_id,
            channel=channel,
            view_count=clip.get("view_count"),
            duration=duration,
        )
        process_clip_pipeline.delay(
            source="twitch_api",
            channel=channel,
            clip_id=clip_id,
            clip_url=clip.get("url", ""),
            clip_thumbnail=clip.get("thumbnail_url", ""),
            triggered_at=time.time(),
        )


async def _main() -> None:
    fetcher = TwitchClipFetcher()
    await fetcher.run()


if __name__ == "__main__":
    asyncio.run(_main())
