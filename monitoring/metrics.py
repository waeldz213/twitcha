"""
Prometheus metrics definitions.

Import individual counters/histograms from here; the HTTP server is in
monitoring/server.py.
"""
from prometheus_client import Counter, Histogram  # type: ignore

CLIPS_DOWNLOADED = Counter(
    "twitcha_clips_downloaded_total",
    "Total number of clips successfully downloaded",
)

CLIPS_PROCESSED = Counter(
    "twitcha_clips_processed_total",
    "Total number of clips that completed the full pipeline",
)

CLIPS_PUBLISHED = Counter(
    "twitcha_clips_published_total",
    "Total number of clips successfully published",
    labelnames=["platform"],
)

PUBLISH_ERRORS = Counter(
    "twitcha_publish_errors_total",
    "Total number of publish failures",
    labelnames=["platform"],
)

PIPELINE_ERRORS = Counter(
    "twitcha_pipeline_errors_total",
    "Total number of pipeline-level errors",
)

PIPELINE_DURATION = Histogram(
    "twitcha_pipeline_duration_seconds",
    "End-to-end pipeline duration in seconds",
    buckets=[30, 60, 120, 300, 600, 1200, 3600],
)

CHAT_SPIKES = Counter(
    "twitcha_chat_spikes_total",
    "Total chat engagement spikes detected",
    labelnames=["source", "channel"],
)
