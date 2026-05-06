"""
core/scheduler.py — APScheduler setup and default jobs.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore

scheduler = AsyncIOScheduler(jobstores={"default": MemoryJobStore()})


def get_scheduler():
    return scheduler


def start_default_jobs():
    from scheduler.jobs import job_sync_portfolio, job_sync_orders

    if not scheduler.get_job("sync_portfolio"):
        scheduler.add_job(
            job_sync_portfolio,
            "interval",
            seconds=30,
            id="sync_portfolio",
            replace_existing=True,
        )

    if not scheduler.get_job("sync_orders"):
        scheduler.add_job(
            job_sync_orders,
            "interval",
            seconds=60,
            id="sync_orders",
            replace_existing=True,
        )
