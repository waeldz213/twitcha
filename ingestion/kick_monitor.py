"""
Kick.com channel monitor via WebSocket.

Kick uses Pusher-compatible WebSocket channels. This monitor connects to
each configured Kick channel's chat and tracks engagement spikes using
the same sliding-window algorithm as the Twitch IRC bot.

NOTE: Kick does not provide an official public API. This implementation
uses the documented public WebSocket endpoints. Always verify compliance
with Kick's Terms of Service before deployment.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from typing import Deque, Dict

import websockets
import structlog

from config.settings import settings
from orchestration.tasks import process_clip_pipeline

log = structlog.get_logger(__name__)

# Kick Pusher app key (public, used by the Kick web client)
KICK_PUSHER_KEY = "eb1d5f283081a78b932c"
KICK_WS_URL = f"wss://ws-us2.pusher.com/app/{KICK_PUSHER_KEY}?protocol=7&client=js&version=7.6.0&flash=false"

COOLDOWN_SECONDS = 90
RECONNECT_DELAY_SECONDS = 10


class KickMonitor:
    """Monitors Kick chat channels for engagement spikes."""

    def __init__(self) -> None:
        self._windows: Dict[str, Deque[tuple[float, int]]] = {}
        self._last_trigger: Dict[str, float] = {}

    async def run(self) -> None:
        log.info("kick_monitor.started", channels=settings.kick_channels)
        tasks = [self._monitor_channel(ch) for ch in settings.kick_channels]
        await asyncio.gather(*tasks)

    async def _monitor_channel(self, channel: str) -> None:
        self._windows[channel] = deque()
        self._last_trigger[channel] = 0.0

        while True:
            try:
                await self._connect_and_listen(channel)
            except Exception:
                log.exception("kick_monitor.error", channel=channel)
            log.info(
                "kick_monitor.reconnecting",
                channel=channel,
                delay=RECONNECT_DELAY_SECONDS,
            )
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)

    async def _connect_and_listen(self, channel: str) -> None:
        async with websockets.connect(KICK_WS_URL, ping_interval=30) as ws:
            # Subscribe to the channel's chat room
            subscribe_msg = json.dumps(
                {
                    "event": "pusher:subscribe",
                    "data": {"auth": "", "channel": f"chatrooms.{channel}.v2"},
                }
            )
            await ws.send(subscribe_msg)
            log.info("kick_monitor.subscribed", channel=channel)

            async for raw in ws:
                try:
                    event = json.loads(raw)
                    await self._handle_event(channel, event)
                except Exception:
                    log.exception("kick_monitor.parse_error", channel=channel)

    async def _handle_event(self, channel: str, event: Dict) -> None:
        event_name: str = event.get("event", "")

        if event_name == "pusher:connection_established":
            return
        if event_name != "App\\Events\\ChatMessageEvent":
            return

        # Parse inner data payload
        data = event.get("data", {})
        if isinstance(data, str):
            data = json.loads(data)

        now = time.monotonic()
        dq = self._windows[channel]
        dq.append((now, 1))

        # Prune old entries
        cutoff = now - settings.chat_window_seconds
        while dq and dq[0][0] < cutoff:
            dq.popleft()

        score = len(dq)

        if score >= settings.chat_spike_threshold:
            if now - self._last_trigger[channel] >= COOLDOWN_SECONDS:
                self._last_trigger[channel] = now
                log.info(
                    "kick.spike_detected",
                    channel=channel,
                    score=score,
                )
                await self._trigger_download(channel)

    async def _trigger_download(self, channel: str) -> None:
        try:
            process_clip_pipeline.delay(
                source="kick",
                channel=channel,
                triggered_at=time.time(),
            )
            log.info("pipeline.enqueued", source="kick", channel=channel)
        except Exception:
            log.exception("pipeline.enqueue_failed", source="kick", channel=channel)


async def _main() -> None:
    monitor = KickMonitor()
    await monitor.run()


if __name__ == "__main__":
    asyncio.run(_main())
