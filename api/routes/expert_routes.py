"""api/routes/expert_routes.py — Expert agent CRUD and execution endpoints."""
from __future__ import annotations
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from core.database import get_session
from core.models import ExpertAgent, ExpertAgentLog
from core.scheduler import get_scheduler
from agents.expert.expert_agent import run_expert_agent

router = APIRouter()


class CreateAgentRequest(BaseModel):
    name: str
    ticker: str
    strategy: str
    schedule: str = ""           # Cron expression (empty = manual only)
    auto_execute: bool = False
    llm_provider: str = "ollama"
    llm_model: str = ""
    llm_temperature: float = 0.7


class UpdateAgentRequest(BaseModel):
    name: Optional[str] = None
    strategy: Optional[str] = None
    schedule: Optional[str] = None
    auto_execute: Optional[bool] = None
    enabled: Optional[bool] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_temperature: Optional[float] = None


@router.get("/api/expert/agents")
def list_agents(db: Session = Depends(get_session)):
    agents = db.query(ExpertAgent).order_by(ExpertAgent.created_at.desc()).all()
    return {
        "agents": [
            {
                "id": a.id,
                "name": a.name,
                "ticker": a.ticker,
                "strategy": a.strategy,
                "schedule": a.schedule,
                "llm_config": json.loads(a.llm_config) if a.llm_config else {},
                "enabled": a.enabled,
                "auto_execute": a.auto_execute,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "last_run": a.last_run.isoformat() if a.last_run else None,
            }
            for a in agents
        ]
    }


@router.post("/api/expert/agents")
def create_agent(req: CreateAgentRequest, db: Session = Depends(get_session)):
    llm_config = {
        "provider": req.llm_provider,
        "model": req.llm_model,
        "temperature": req.llm_temperature,
    }

    agent = ExpertAgent(
        name=req.name,
        ticker=req.ticker.upper(),
        strategy=req.strategy,
        schedule=req.schedule,
        llm_config=json.dumps(llm_config),
        enabled=True,
        auto_execute=req.auto_execute,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)

    # Set up scheduler job if schedule provided
    if req.schedule and req.schedule.strip():
        _setup_schedule(agent, db)

    return {"success": True, "agent_id": agent.id, "name": agent.name}


@router.put("/api/expert/agents/{agent_id}")
def update_agent(agent_id: int, req: UpdateAgentRequest,
                 db: Session = Depends(get_session)):
    agent = db.query(ExpertAgent).filter(ExpertAgent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if req.name is not None:
        agent.name = req.name
    if req.strategy is not None:
        agent.strategy = req.strategy
    if req.auto_execute is not None:
        agent.auto_execute = req.auto_execute
    if req.enabled is not None:
        agent.enabled = req.enabled

    # Update LLM config
    current_config = json.loads(agent.llm_config) if agent.llm_config else {}
    if req.llm_provider is not None:
        current_config["provider"] = req.llm_provider
    if req.llm_model is not None:
        current_config["model"] = req.llm_model
    if req.llm_temperature is not None:
        current_config["temperature"] = req.llm_temperature
    agent.llm_config = json.dumps(current_config)

    # Update schedule
    if req.schedule is not None:
        agent.schedule = req.schedule
        _remove_schedule(agent)
        if req.schedule.strip():
            _setup_schedule(agent, db)

    db.commit()
    return {"success": True, "agent_id": agent.id}


@router.delete("/api/expert/agents/{agent_id}")
def delete_agent(agent_id: int, db: Session = Depends(get_session)):
    agent = db.query(ExpertAgent).filter(ExpertAgent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    _remove_schedule(agent)
    db.query(ExpertAgentLog).filter(ExpertAgentLog.agent_id == agent_id).delete()
    db.delete(agent)
    db.commit()
    return {"success": True}


@router.post("/api/expert/agents/{agent_id}/run")
async def run_agent_now(agent_id: int, db: Session = Depends(get_session)):
    """Manually trigger an expert agent run."""
    agent = db.query(ExpertAgent).filter(ExpertAgent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    import asyncio
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: run_expert_agent(agent_id))

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/api/expert/agents/{agent_id}/logs")
def get_agent_logs(agent_id: int, limit: int = 20,
                   db: Session = Depends(get_session)):
    logs = (
        db.query(ExpertAgentLog)
        .filter(ExpertAgentLog.agent_id == agent_id)
        .order_by(ExpertAgentLog.timestamp.desc())
        .limit(limit)
        .all()
    )
    return {
        "logs": [
            {
                "id": l.id,
                "timestamp": l.timestamp.isoformat() if l.timestamp else None,
                "decision": l.decision,
                "reasoning": l.reasoning,
                "executed": l.executed,
                "order_id": l.order_id,
                "error": l.error,
            }
            for l in logs
        ]
    }


def _setup_schedule(agent: ExpertAgent, db: Session):
    """Register a cron job in APScheduler for this agent."""
    scheduler = get_scheduler()
    job_id = f"expert_{agent.id}"

    parts = agent.schedule.split()
    if len(parts) != 5:
        return

    minute, hour, day, month, dow = parts
    try:
        scheduler.add_job(
            run_expert_agent, "cron",
            minute=minute, hour=hour, day=day, month=month, day_of_week=dow,
            id=job_id, replace_existing=True,
            kwargs={"agent_id": agent.id},
        )
        agent.scheduler_job_id = job_id
        db.commit()
    except Exception as e:
        print(f"[Expert] Schedule error for agent {agent.id}: {e}")


def _remove_schedule(agent: ExpertAgent):
    """Remove the scheduler job for this agent."""
    scheduler = get_scheduler()
    if agent.scheduler_job_id:
        try:
            scheduler.remove_job(agent.scheduler_job_id)
        except Exception:
            pass
        agent.scheduler_job_id = None
