"""
AI Enrichment – generates compelling titles, descriptions, and hashtags
for short-form clips using OpenAI GPT-4o-mini (or a compatible model).

Input:  transcript text + channel/streamer context
Output: {
    "title":       "OMG he 1v5'd the whole team 😱",
    "description": "...",
    "hashtags":    ["#Twitch", "#Gaming", ...]
}
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import structlog
from openai import OpenAI

from config.settings import settings

log = structlog.get_logger(__name__)

_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


SYSTEM_PROMPT = """\
You are a social media expert specializing in viral short-form video content
for gaming and streaming platforms (TikTok, Instagram Reels, YouTube Shorts).

Given a clip transcript and context, generate:
1. A punchy, attention-grabbing title (max 80 chars, use emojis sparingly but effectively).
2. A short description (max 150 chars) suited for the caption.
3. Exactly 5 relevant hashtags without the # prefix.

Respond ONLY with a JSON object in this exact schema:
{
  "title": "...",
  "description": "...",
  "hashtags": ["tag1", "tag2", "tag3", "tag4", "tag5"]
}
"""


def enrich_clip(
    transcript_text: str,
    channel_name: str,
    platform: str = "TikTok",
    extra_context: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate title, description, and hashtags for a clip.

    Falls back to placeholder values on API failure so the pipeline
    is never blocked by enrichment errors.
    """
    if not settings.openai_api_key:
        log.warning("enricher.no_api_key; using placeholders")
        return _fallback(channel_name)

    context_block = f"\nExtra context: {extra_context}" if extra_context else ""
    user_message = (
        f"Platform: {platform}\n"
        f"Channel / Streamer: {channel_name}\n"
        f"Transcript:\n{transcript_text[:1500]}"
        f"{context_block}"
    )

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.7,
            max_tokens=300,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)

        title: str = data.get("title", f"{channel_name} clip")[:80]
        description: str = data.get("description", "")[:150]
        hashtags: List[str] = data.get("hashtags", [])[:5]

        log.info("enricher.done", title=title, hashtag_count=len(hashtags))
        return {"title": title, "description": description, "hashtags": hashtags}

    except Exception:
        log.exception("enricher.api_error; falling back")
        return _fallback(channel_name)


def _fallback(channel_name: str) -> Dict[str, Any]:
    return {
        "title": f"{channel_name} – Best Moments",
        "description": f"Best clip from {channel_name} 🎮",
        "hashtags": ["Twitch", "Gaming", "Clip", "Streamer", "Shorts"],
    }


def build_caption(enriched: Dict[str, Any]) -> str:
    """Format the enriched data into a ready-to-use social media caption."""
    tags = " ".join(f"#{t}" for t in enriched.get("hashtags", []))
    return f"{enriched['title']}\n\n{enriched.get('description', '')}\n\n{tags}".strip()
