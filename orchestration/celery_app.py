"""
Celery application instance.

Broker  : Redis
Backend : Redis

All tasks are defined in orchestration/tasks.py.
"""
from celery import Celery  # type: ignore

from config.settings import settings

app = Celery(
    "twitcha",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["orchestration.tasks"],
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    worker_max_tasks_per_child=50,  # recycle workers to avoid memory leaks
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Beat schedule: periodic clip poll from Twitch API
    beat_schedule={
        "poll-twitch-clips-every-2min": {
            "task": "orchestration.tasks.poll_twitch_clips",
            "schedule": 120.0,
        },
    },
)
