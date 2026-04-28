"""
Twitch IRC chat bot – real-time engagement monitoring.

Listens to one or more Twitch channels via IRC-over-WebSocket (TwitchIO).
Maintains a sliding window of message timestamps and triggers a clip download
task whenever the messages-per-window exceed `chat_spike_threshold`.

Key emotes that amplify the spike score:
    KEKW, PogChamp, Pog, LUL, OMEGALUL, 5Head, LULW, monkaS, NOTED, KEKW
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Deque, Dict

import structlog
from twitchio.ext import commands  # type: ignore

from config.settings import settings
from orchestration.tasks import process_clip_pipeline

log = structlog.get_logger(__name__)

# High-engagement emotes add extra weight to the spike score.
HYPE_EMOTES: frozenset[str] = frozenset(
    {
        "KEKW", "PogChamp", "Pog", "PogU", "LUL", "OMEGALUL",
        "LULW", "monkaS", "5Head", "NOTED", "POGGERS", "PauseChamp",
        "FeelsStrongMan", "Clap", "EZ", "HeyGuys",
    }
)
EMOTE_WEIGHT = 2  # each hype emote counts as N messages
COOLDOWN_SECONDS = 90  # min seconds between consecutive triggers per channel


class TwitchBot(commands.Bot):
    """IRC bot that tracks engagement spikes and triggers clip downloads."""

    def __init__(self) -> None:
        super().__init__(
            token=settings.twitch_oauth_token,
            prefix="!",
            initial_channels=settings.twitch_channels,
        )
        # channel_name → deque of (timestamp, weight) tuples
        self._windows: Dict[str, Deque[tuple[float, int]]] = {
            ch: deque() for ch in settings.twitch_channels
        }
        self._last_trigger: Dict[str, float] = {
            ch: 0.0 for ch in settings.twitch_channels
        }

    # ── TwitchIO events ─────────────────────────────────────────────────────

    async def event_ready(self) -> None:
        log.info("twitch_bot.ready", nick=self.nick, channels=settings.twitch_channels)

    async def event_message(self, message) -> None:
        if message.echo:
            return

        channel = message.channel.name
        now = time.monotonic()
        window_sec = settings.chat_window_seconds

        # Determine message weight
        weight = 1
        if message.content:
            for word in message.content.split():
                if word in HYPE_EMOTES:
                    weight += EMOTE_WEIGHT

        # Maintain sliding window
        dq = self._windows.setdefault(channel, deque())
        dq.append((now, weight))
        cutoff = now - window_sec
        while dq and dq[0][0] < cutoff:
            dq.popleft()

        # Compute weighted score
        score = sum(w for _, w in dq)

        if score >= settings.chat_spike_threshold:
            if now - self._last_trigger.get(channel, 0.0) >= COOLDOWN_SECONDS:
                self._last_trigger[channel] = now
                log.info(
                    "chat.spike_detected",
                    channel=channel,
                    score=score,
                    threshold=settings.chat_spike_threshold,
                )
                await self._trigger_download(channel)

    # ── Internal helpers ────────────────────────────────────────────────────

    async def _trigger_download(self, channel: str) -> None:
        """Fire-and-forget: enqueue the clip download + pipeline task."""
        try:
            process_clip_pipeline.delay(
                source="twitch",
                channel=channel,
                triggered_at=time.time(),
            )
            log.info("pipeline.enqueued", channel=channel)
        except Exception:
            log.exception("pipeline.enqueue_failed", channel=channel)


def run() -> None:
    bot = TwitchBot()
    bot.run()


if __name__ == "__main__":
    run()
