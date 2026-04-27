# twitcha 🎬

> Automated live-clipping pipeline: **Twitch / Kick → Short-Form Video → TikTok / Reels / YouTube Shorts**

```
[Live Twitch/Kick] → [Bot Détection] → [Downloader] → [IA & Montage] → [Publisher]
```

---

## Architecture

```
twitcha/
├── config/              # Pydantic settings (env vars)
├── ingestion/           # Chat bots, Twitch API poller, yt-dlp downloader
├── processing/          # Whisper transcription, smart crop, MoviePy editor, Remotion renderer
├── remotion/            # React/TypeScript animated subtitle template
├── enrichment/          # OpenAI GPT title/description/hashtag generation
├── publisher/           # Playwright-based TikTok / Instagram / YouTube uploaders
├── orchestration/       # Celery + Redis task queue
├── monitoring/          # Prometheus metrics
└── data/                # clips/, processed/, renders/, cookies/ (gitignored)
```

---

## Quick Start

### 1. Prerequisites

- Python 3.11+
- Node.js 20+ (for Remotion)
- FFmpeg
- Redis

### 2. Install

```bash
cp .env.example .env
# Edit .env with your API keys and channel names

pip install -r requirements.txt
playwright install chromium --with-deps

cd remotion && npm install && cd ..
```

### 3. Run with Docker Compose

```bash
docker compose up --build
```

This starts:
- `redis` – broker/backend
- `worker` – Celery worker (pipeline tasks)
- `beat` – Celery Beat (periodic Twitch clip polling)
- `bot` – Twitch IRC chat bot
- `kick_monitor` – Kick WebSocket monitor
- `metrics` – Prometheus metrics server (`:8000`)

### 4. Run manually (development)

```bash
# Terminal 1 – Redis
docker run -p 6379:6379 redis:7-alpine

# Terminal 2 – Celery worker
celery -A orchestration.celery_app worker --loglevel=info

# Terminal 3 – Celery Beat (periodic polling)
celery -A orchestration.celery_app beat --loglevel=info

# Terminal 4 – Twitch IRC bot
python -m ingestion.twitch_bot

# Terminal 5 – Kick monitor
python -m ingestion.kick_monitor

# Terminal 6 – Metrics
python -m monitoring.server
```

---

## Pipeline Steps

| Step | Module | Description |
|------|--------|-------------|
| 1 | `ingestion/twitch_bot.py` | IRC bot monitors chat, detects engagement spikes |
| 1b | `ingestion/clip_fetcher.py` | Polls Twitch API `/clips` every 2 min |
| 1c | `ingestion/kick_monitor.py` | Kick WebSocket chat monitor |
| 2 | `ingestion/downloader.py` | Downloads clip via yt-dlp or live segment via streamlink |
| 3 | `processing/smart_crop.py` | MediaPipe face detection → FFmpeg 9:16 crop |
| 4 | `processing/transcriber.py` | Whisper local / AssemblyAI transcription |
| 5 | `processing/editor.py` | Trim, audio normalization, optional subtitle burn |
| 6 | `processing/remotion_renderer.py` | Remotion renders branded clip with animated subtitles |
| 7 | `enrichment/ai_enricher.py` | GPT-4o-mini generates title, description, hashtags |
| 8 | `publisher/dispatcher.py` | Posts to TikTok, Instagram Reels, YouTube Shorts |

---

## Configuration

All settings live in `.env` (see `.env.example`):

| Variable | Description |
|----------|-------------|
| `TWITCH_CHANNELS` | Comma-separated channel names to monitor |
| `KICK_CHANNELS` | Comma-separated Kick channels |
| `CHAT_SPIKE_THRESHOLD` | Messages/window to trigger a clip (default: 20) |
| `CHAT_WINDOW_SECONDS` | Sliding window size in seconds (default: 10) |
| `WHISPER_MODEL` | Whisper model size (`tiny`→`large-v3`) |
| `USE_ASSEMBLYAI` | Set `true` to use AssemblyAI instead of local Whisper |
| `OPENAI_API_KEY` | OpenAI API key for enrichment |
| `PROXY_LIST` | Comma-separated `http://user:pass@host:port` proxies |
| `PUBLISH_TIKTOK` | Enable TikTok publishing (default: `true`) |
| `PUBLISH_INSTAGRAM` | Enable Instagram publishing (default: `true`) |
| `PUBLISH_YOUTUBE` | Enable YouTube publishing (default: `true`) |

---

## Cost Estimate

| Component | Free / OSS | SaaS | Cost/clip |
|-----------|-----------|------|-----------|
| Transcription | Whisper local | AssemblyAI | $0 / ~$0.05 |
| Editing | MoviePy + FFmpeg | – | $0 |
| Rendering | Remotion (self-hosted) | – | ~$0.02 (GPU) |
| AI enrichment | – | GPT-4o-mini | ~$0.001 |
| Proxy | – | Residential | ~$0.10 |
| **Total** | | | **~$0.15/clip** |

---

## Anti-Detection Notes

- Publishers use **Playwright** with randomised delays (not public APIs).
- Each platform uses a **different residential proxy**.
- **Cookies are persisted** per account to avoid repeated logins.
- **User-agents** are rotated to simulate real mobile devices.
- Posts are spread with **20–60 min random gaps** between platforms.

---

## Monitoring

Prometheus metrics are exposed at `http://localhost:8000/metrics`:

| Metric | Description |
|--------|-------------|
| `twitcha_clips_downloaded_total` | Downloads succeeded |
| `twitcha_clips_processed_total` | Full pipeline completions |
| `twitcha_clips_published_total{platform}` | Successful publishes per platform |
| `twitcha_publish_errors_total{platform}` | Publish failures per platform |
| `twitcha_pipeline_duration_seconds` | End-to-end latency histogram |

---

## License

MIT