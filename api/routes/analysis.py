"""api/routes/analysis.py — Debate analysis endpoints."""
from __future__ import annotations
import asyncio
import json
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from core.database import get_session
from core.models import Analysis
from pipeline.analysis_pipeline import run_analysis

router = APIRouter()


class AnalysisRequest(BaseModel):
    ticker: str
    rounds: int = 1
    include_hold: bool = False
    auto_execute: bool = False
    skip_judges: bool = False
    skip_factcheck: bool = False


@router.post("/api/analysis/run")
async def start_analysis(req: AnalysisRequest, background_tasks: BackgroundTasks,
                         db: Session = Depends(get_session)):
    analysis = Analysis(ticker=req.ticker.upper(), status="queued")
    db.add(analysis)
    db.commit()
    analysis_id = analysis.id
    loop        = asyncio.get_event_loop()

    background_tasks.add_task(
        run_analysis,
        ticker=req.ticker.upper(), analysis_id=analysis_id,
        rounds=req.rounds, include_hold=req.include_hold,
        auto_execute=req.auto_execute,
        skip_judges=req.skip_judges, skip_factcheck=req.skip_factcheck,
        loop=loop,
    )
    return {"analysis_id": analysis_id, "ticker": req.ticker.upper(), "status": "started"}


@router.get("/api/analysis/history")
def get_history(limit: int = 20, db: Session = Depends(get_session)):
    rows = db.query(Analysis).order_by(Analysis.timestamp.desc()).limit(limit).all()
    return {
        "analyses": [
            {"id": a.id, "ticker": a.ticker, "decision": a.final_decision,
             "confidence": a.confidence_score, "label": a.confidence_label,
             "status": a.status, "timestamp": a.timestamp.isoformat() if a.timestamp else None}
            for a in rows
        ]
    }


@router.get("/api/analysis/{analysis_id}")
def get_analysis(analysis_id: int, db: Session = Depends(get_session)):
    a = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return {
        "id": a.id, "ticker": a.ticker, "status": a.status,
        "decision": a.final_decision, "confidence": a.confidence_score,
        "label": a.confidence_label,
        "verdict": json.loads(a.verdict) if a.verdict else None,
        "transcript": json.loads(a.debate_transcript) if a.debate_transcript else [],
        "timestamp": a.timestamp.isoformat() if a.timestamp else None,
    }
