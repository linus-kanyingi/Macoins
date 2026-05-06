"""api/routes/scheduler_routes.py — Scheduled job management endpoints."""
from __future__ import annotations
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from core.database import get_session
from core.models import ScheduledJob
from core.scheduler import get_scheduler
from scheduler.jobs import job_scheduled_analysis

router = APIRouter()


class JobRequest(BaseModel):
    ticker: str
    job_type: str = "analysis"
    cron_expr: str
    rounds: int = 1
    auto_execute: bool = False


@router.get("/api/jobs")
def list_jobs(db: Session = Depends(get_session)):
    jobs = db.query(ScheduledJob).order_by(ScheduledJob.created_at.desc()).all()
    return {
        "jobs": [
            {"id": j.id, "job_id": j.job_id, "ticker": j.ticker, "job_type": j.job_type,
             "cron_expr": j.cron_expr, "enabled": j.enabled,
             "last_run": j.last_run.isoformat() if j.last_run else None}
            for j in jobs
        ]
    }


@router.post("/api/jobs")
def create_job(req: JobRequest, db: Session = Depends(get_session)):
    scheduler = get_scheduler()
    job_id    = f"{req.ticker.upper()}_{req.job_type}_{int(datetime.utcnow().timestamp())}"

    parts = req.cron_expr.split()
    if len(parts) != 5:
        raise HTTPException(status_code=400, detail="cron_expr must have 5 fields: min hour day month weekday")
    minute, hour, day, month, dow = parts

    scheduler.add_job(
        job_scheduled_analysis, "cron",
        minute=minute, hour=hour, day=day, month=month, day_of_week=dow,
        id=job_id, replace_existing=True,
        kwargs={"ticker": req.ticker.upper(), "rounds": req.rounds, "auto_execute": req.auto_execute},
    )

    job = ScheduledJob(
        job_id=job_id, ticker=req.ticker.upper(),
        job_type=req.job_type, cron_expr=req.cron_expr, enabled=True,
    )
    db.add(job)
    db.commit()
    return {"success": True, "job_id": job_id}


@router.delete("/api/jobs/{job_id}")
def delete_job(job_id: str, db: Session = Depends(get_session)):
    scheduler = get_scheduler()
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass
    db.query(ScheduledJob).filter(ScheduledJob.job_id == job_id).delete()
    db.commit()
    return {"success": True}


@router.post("/api/jobs/{job_id}/run")
def run_job_now(job_id: str):
    scheduler = get_scheduler()
    job = scheduler.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.modify(next_run_time=datetime.utcnow())
    return {"success": True, "job_id": job_id}
