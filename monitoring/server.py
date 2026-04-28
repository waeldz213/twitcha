"""
Prometheus HTTP metrics server.

Run as a standalone process:
    python -m monitoring.server

Or import `start_metrics_server()` to embed in another process.
"""
from __future__ import annotations

import structlog
from prometheus_client import start_http_server  # type: ignore

from config.settings import settings

log = structlog.get_logger(__name__)


def start_metrics_server(port: int | None = None) -> None:
    actual_port = port or settings.prometheus_port
    start_http_server(actual_port)
    log.info("metrics.server_started", port=actual_port)


if __name__ == "__main__":
    import time

    start_metrics_server()
    log.info("metrics.running", port=settings.prometheus_port)
    while True:
        time.sleep(60)
