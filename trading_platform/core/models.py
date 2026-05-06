"""
core/models.py — All SQLAlchemy ORM models.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text
from core.database import Base


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True)
    order_id = Column(String, unique=True, index=True)
    ticker = Column(String)
    side = Column(String)  # BUY/SELL
    qty = Column(Float)
    price = Column(Float, nullable=True)
    status = Column(String)  # accepted/filled/cancelled
    source = Column(String, default="manual")  # manual/analysis/expert
    analysis_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    filled_at = Column(DateTime, nullable=True)
    pnl = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)


class Analysis(Base):
    """A full analysis run — factor research → debate → verdict."""
    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True)
    ticker = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="running")  # running/done/failed
    final_decision = Column(String, nullable=True)  # BUY/SELL/HOLD
    confidence_score = Column(Float, nullable=True)
    confidence_label = Column(String, nullable=True)

    # JSON: list of identified factors
    factors = Column(Text, nullable=True)
    # JSON: list of research reports (one per factor)
    research_reports = Column(Text, nullable=True)
    # JSON: debate transcript (bull and bear arguments)
    debate_transcript = Column(Text, nullable=True)
    # JSON: full verdict with reasoning
    verdict = Column(Text, nullable=True)

    auto_executed = Column(Boolean, default=False)


class ExpertAgent(Base):
    """A user-configured autonomous trading agent for a specific stock."""
    __tablename__ = "expert_agents"

    id = Column(Integer, primary_key=True)
    name = Column(String)
    ticker = Column(String)
    strategy = Column(Text)            # User's strategy instructions (free text)
    schedule = Column(String)          # Cron expression (e.g. "0 9 * * 1-5")
    llm_config = Column(Text)          # JSON: LLMConfig dict
    enabled = Column(Boolean, default=True)
    auto_execute = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_run = Column(DateTime, nullable=True)
    scheduler_job_id = Column(String, nullable=True)


class ExpertAgentLog(Base):
    """Log of each expert agent run."""
    __tablename__ = "expert_agent_logs"

    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    market_data = Column(Text, nullable=True)    # JSON: snapshot of market data used
    reasoning = Column(Text, nullable=True)      # LLM reasoning output
    decision = Column(String, nullable=True)     # BUY/SELL/HOLD
    executed = Column(Boolean, default=False)
    order_id = Column(String, nullable=True)
    error = Column(Text, nullable=True)


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id = Column(Integer, primary_key=True)
    job_id = Column(String, unique=True)
    ticker = Column(String)
    job_type = Column(String)  # analysis/expert
    cron_expr = Column(String)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_run = Column(DateTime, nullable=True)
    params = Column(Text, nullable=True)  # JSON


class RiskLog(Base):
    __tablename__ = "risk_logs"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    event_type = Column(String)  # stop_loss/max_positions/drawdown/approved
    ticker = Column(String, nullable=True)
    message = Column(Text)
