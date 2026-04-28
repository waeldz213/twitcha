"""
Central configuration loaded from environment variables / .env file.
All other modules import `settings` from here.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Twitch ──────────────────────────────────────────────────────────────
    twitch_client_id: str = ""
    twitch_client_secret: str = ""
    twitch_oauth_token: str = ""
    twitch_bot_nick: str = "twitcha_bot"
    twitch_channels: List[str] = Field(default_factory=list)

    # ── Kick ────────────────────────────────────────────────────────────────
    kick_channels: List[str] = Field(default_factory=list)

    # ── OpenAI ──────────────────────────────────────────────────────────────
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # ── AssemblyAI ──────────────────────────────────────────────────────────
    assemblyai_api_key: str = ""
    use_assemblyai: bool = False

    # ── Whisper ─────────────────────────────────────────────────────────────
    whisper_model: str = "large-v3"
    whisper_device: str = "cpu"

    # ── Redis / Celery ───────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    celery_concurrency: int = 2

    # ── Storage ─────────────────────────────────────────────────────────────
    clips_dir: Path = Path("./data/clips")
    processed_dir: Path = Path("./data/processed")
    renders_dir: Path = Path("./data/renders")
    cookies_dir: Path = Path("./data/cookies")

    # ── Pipeline thresholds ─────────────────────────────────────────────────
    chat_spike_threshold: int = 20
    chat_window_seconds: int = 10
    clip_min_duration: int = 20
    clip_max_duration: int = 60

    # ── Proxies ─────────────────────────────────────────────────────────────
    proxy_list: List[str] = Field(default_factory=list)

    # ── Publisher toggles ───────────────────────────────────────────────────
    publish_tiktok: bool = True
    publish_instagram: bool = True
    publish_youtube: bool = True

    # ── Monitoring ──────────────────────────────────────────────────────────
    prometheus_port: int = 8000

    def ensure_dirs(self) -> None:
        for d in (self.clips_dir, self.processed_dir, self.renders_dir, self.cookies_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
