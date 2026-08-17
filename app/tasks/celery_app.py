"""JobPilot Celery 应用配置。"""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "jobpilot",
    broker=settings.celery_broker_url.get_secret_value(),
    backend=settings.celery_result_backend.get_secret_value(),
    include=["app.tasks.resume_ingestion_task"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    result_expires=86_400,
    task_soft_time_limit=settings.celery_task_soft_time_limit_seconds,
    task_time_limit=settings.celery_task_time_limit_seconds,
    timezone="Asia/Shanghai",
    enable_utc=True,
)
