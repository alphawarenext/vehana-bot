from celery import Celery
from celery.schedules import crontab
from core.config import settings

celery_app = Celery(
    "vehana",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["workers.campaign_tasks", "workers.analytics_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_acks_late=True,          # only ack after task completes (safe retries)
    worker_prefetch_multiplier=1, # one task at a time per worker (fair for long calls)
    task_track_started=True,
)

# ─── Scheduled jobs (Celery Beat) ────────────────────────────────────────────
celery_app.conf.beat_schedule = {
    # Aggregate yesterday's call stats into DailyCallStats at 1am IST
    "nightly-analytics": {
        "task": "workers.analytics_tasks.aggregate_daily_stats",
        "schedule": crontab(hour=1, minute=0),
    },
    # Reset monthly call quotas on billing reset date
    "monthly-quota-reset": {
        "task": "workers.analytics_tasks.reset_monthly_quotas",
        "schedule": crontab(hour=0, minute=30),
    },
    # Update monthly_cost_usd on all orgs from usage_event rows
    "update-org-costs": {
        "task": "workers.analytics_tasks.update_org_monthly_costs",
        "schedule": crontab(minute="*/30"),  # every 30 min
    },
}
