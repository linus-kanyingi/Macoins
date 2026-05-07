"""api/routes/analysis_routes.py — Analysis pipeline endpoints."""
from __future__ import annotations
import asyncio
import json
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from core.database import get_session
from core.models import Analysis
from agents.analysis.analysis_orchestrator import run_analysis, cancel_analysis
from agents.analysis.stock_picker import suggest_stocks
from agents.llm_router import LLMConfig

router = APIRouter()


class AnalysisRequest(BaseModel):
    ticker: str
    auto_execute: bool = False
    llm_provider: str = "ollama"
    llm_model: str = ""
    llm_think: bool = True


class StockSuggestRequest(BaseModel):
    llm_provider: str = "ollama"
    llm_model: str = ""
    llm_think: bool = True


@router.post("/api/analysis/suggest-stocks")
async def suggest_stocks_route(req: StockSuggestRequest):
    """Suggest top 3 stocks for analysis (for beginners)."""
    loop = asyncio.get_event_loop()
    config = LLMConfig(
        provider=req.llm_provider,
        model=req.llm_model or "",
        label="Stock Picker",
        max_tokens=300,
        think=req.llm_think,
    )

    try:
        suggestions = await loop.run_in_executor(
            None, lambda: suggest_stocks(config=config)
        )
        return {"suggestions": suggestions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/analysis/run")
async def start_analysis(req: AnalysisRequest, background_tasks: BackgroundTasks,
                         db: Session = Depends(get_session)):
    """Start a full analysis pipeline for a stock."""
    analysis = Analysis(ticker=req.ticker.upper(), status="queued")
    db.add(analysis)
    db.commit()
    analysis_id = analysis.id
    loop = asyncio.get_event_loop()

    config = LLMConfig(
        provider=req.llm_provider,
        model=req.llm_model or "",
        max_tokens=300,
        think=req.llm_think,
    )

    background_tasks.add_task(
        run_analysis,
        ticker=req.ticker.upper(),
        analysis_id=analysis_id,
        config=config,
        auto_execute=req.auto_execute,
        loop=loop,
    )
    return {"analysis_id": analysis_id, "ticker": req.ticker.upper(), "status": "started"}


@router.post("/api/analysis/{analysis_id}/cancel")
def cancel_analysis_route(analysis_id: int):
    """Cancel a running analysis."""
    cancelled = cancel_analysis(analysis_id)
    if cancelled:
        return {"success": True, "message": f"Analysis {analysis_id} cancellation requested"}
    return {"success": False, "message": "Analysis not found or not running"}


@router.get("/api/analysis/history")
def get_history(limit: int = 20, db: Session = Depends(get_session)):
    rows = db.query(Analysis).order_by(Analysis.timestamp.desc()).limit(limit).all()
    return {
        "analyses": [
            {
                "id": a.id,
                "ticker": a.ticker,
                "decision": a.final_decision,
                "confidence": a.confidence_score,
                "label": a.confidence_label,
                "status": a.status,
                "timestamp": a.timestamp.isoformat() if a.timestamp else None,
            }
            for a in rows
        ]
    }


@router.get("/api/analysis/{analysis_id}")
def get_analysis(analysis_id: int, db: Session = Depends(get_session)):
    a = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return {
        "id": a.id,
        "ticker": a.ticker,
        "status": a.status,
        "decision": a.final_decision,
        "confidence": a.confidence_score,
        "label": a.confidence_label,
        "factors": json.loads(a.factors) if a.factors else [],
        "research_reports": json.loads(a.research_reports) if a.research_reports else [],
        "debate_transcript": json.loads(a.debate_transcript) if a.debate_transcript else [],
        "verdict": json.loads(a.verdict) if a.verdict else None,
        "timestamp": a.timestamp.isoformat() if a.timestamp else None,
    }
