"""
agents/analysis/analysis_orchestrator.py — Orchestrates the full analysis pipeline.

Flow:
1. Market data gathering
2. Factor identification (broadcast factors found)
3. Spawn research agents in parallel (broadcast each report)
4. Debate phase (broadcast arguments)
5. Judging phase (broadcast verdict)
6. Save to DB
"""
from __future__ import annotations
import asyncio
import json
import traceback
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from agents.llm_router import LLMConfig, default_config
from agents.analysis.factor_identifier import identify_factors
from agents.analysis.research_agent import research_factor
from agents.analysis.debate_agent import debate_opening, debate_rebuttal, debate_closing
from agents.analysis.judge_agent import judge_debate
from agents.trading.market_data_agent import market_data_agent
from core import events
from core.database import SessionLocal
from core.models import Analysis

_executor = ThreadPoolExecutor(max_workers=6)

# ── Cancellation registry ─────────────────────────────────────────────────────
# Maps analysis_id -> threading.Event (set = cancelled)
_cancel_flags: dict[int, threading.Event] = {}


def cancel_analysis(analysis_id: int) -> bool:
    """Request cancellation of a running analysis. Returns True if it was running."""
    flag = _cancel_flags.get(analysis_id)
    if flag:
        flag.set()
        print(f"[Pipeline] Cancellation requested for analysis {analysis_id}")
        return True
    return False


def is_cancelled(analysis_id: int) -> bool:
    flag = _cancel_flags.get(analysis_id)
    return flag.is_set() if flag else False


class AnalysisCancelled(Exception):
    pass


def _check_cancel(analysis_id: int):
    """Raise AnalysisCancelled if cancellation was requested."""
    if is_cancelled(analysis_id):
        raise AnalysisCancelled(f"Analysis {analysis_id} was cancelled by user")


async def run_analysis(
    ticker: str,
    analysis_id: int,
    config: Optional[LLMConfig] = None,
    auto_execute: bool = False,
    loop=None,
) -> dict:
    """
    Run the full analysis pipeline for a stock.
    Broadcasts progress via WebSocket at each step.
    """
    loop = loop or asyncio.get_event_loop()
    db = SessionLocal()
    ticker = ticker.upper()

    if config is None:
        config = default_config()

    # Register cancellation flag
    cancel_flag = threading.Event()
    _cancel_flags[analysis_id] = cancel_flag

    try:
        # Mark running
        analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        if analysis:
            analysis.status = "running"
            db.commit()

        # ── Token streaming callback factory ──
        def make_token_cb(step: str, agent: str):
            """Create a callback that broadcasts each token via WebSocket."""
            def on_token(token: str):
                events.manager.broadcast_sync({
                    "type": events.EVT_ANALYSIS_TOKEN,
                    "analysis_id": analysis_id,
                    "step": step,
                    "agent": agent,
                    "token": token,
                }, loop)
            return on_token

        # ── Step 1: Build market data scenario ──
        print(f"\n{'='*60}\n  ANALYSIS: {ticker}\n{'='*60}")
        print("[Step 1] Gathering market data...")

        scenario = await loop.run_in_executor(
            _executor, lambda: market_data_agent.build_scenario(ticker)
        )
        market_data = scenario.evidence_packet()
        _check_cancel(analysis_id)

        await events.manager.broadcast({
            "type": events.EVT_ANALYSIS_STARTED,
            "analysis_id": analysis_id,
            "ticker": ticker,
            "price": scenario.current_price,
        })

        # ── Step 2: Identify factors ──
        print(f"\n[Step 2] Identifying key factors for {ticker}...")

        factors = await loop.run_in_executor(
            _executor, lambda: identify_factors(
                ticker, config=config,
                token_callback=make_token_cb("factors", "Factor Identifier"),
            )
        )
        _check_cancel(analysis_id)

        await events.manager.broadcast({
            "type": events.EVT_FACTORS_IDENTIFIED,
            "analysis_id": analysis_id,
            "ticker": ticker,
            "factors": factors,
        })

        # ── Step 3: Research each factor (parallel) ──
        print(f"\n[Step 3] Spawning {len(factors)} research agents...")

        await events.manager.broadcast({
            "type": events.EVT_RESEARCH_STARTED,
            "analysis_id": analysis_id,
            "ticker": ticker,
            "factor_count": len(factors),
        })

        research_reports = []

        # Run research agents — sequentially to avoid Ollama contention
        # (Ollama has a single-request lock), but parallel for cloud APIs
        for i, factor in enumerate(factors):
            _check_cancel(analysis_id)

            agent_label = f"Research: {factor['factor_name']}"
            agent_config = LLMConfig(
                provider=config.provider,
                model=config.model,
                temperature=config.temperature,
                max_tokens=400,
                label=agent_label,
            )

            print(f"\n  [{i+1}/{len(factors)}] Researching: {factor['factor_name']}")

            report = await loop.run_in_executor(
                _executor,
                lambda f=factor, c=agent_config: research_factor(
                    ticker, f, market_data=market_data, config=c,
                    token_callback=make_token_cb("research", f['factor_name']),
                ),
            )
            report_dict = report.to_dict()
            research_reports.append(report_dict)

            await events.manager.broadcast({
                "type": events.EVT_RESEARCH_REPORT,
                "analysis_id": analysis_id,
                "ticker": ticker,
                "report_index": i,
                "report": report_dict,
            })

        # ── Step 4: Debate ──
        _check_cancel(analysis_id)
        print(f"\n[Step 4] Starting debate — BULL vs BEAR...")

        debate_transcript = []

        # Bull opening
        print("\n  BULL — Opening argument...")
        bull_open = await loop.run_in_executor(
            _executor,
            lambda: debate_opening(
                ticker, "bull", research_reports, market_data, config=config,
                token_callback=make_token_cb("debate", "BULL Opening"),
            ),
        )
        debate_transcript.append(bull_open.to_dict())
        await events.manager.broadcast({
            "type": events.EVT_DEBATE_ARGUMENT,
            "analysis_id": analysis_id,
            "ticker": ticker,
            "argument": bull_open.to_dict(),
        })

        _check_cancel(analysis_id)

        # Bear opening
        print("\n  BEAR — Opening argument...")
        bear_open = await loop.run_in_executor(
            _executor,
            lambda: debate_opening(
                ticker, "bear", research_reports, market_data, config=config,
                token_callback=make_token_cb("debate", "BEAR Opening"),
            ),
        )
        debate_transcript.append(bear_open.to_dict())
        await events.manager.broadcast({
            "type": events.EVT_DEBATE_ARGUMENT,
            "analysis_id": analysis_id,
            "ticker": ticker,
            "argument": bear_open.to_dict(),
        })

        _check_cancel(analysis_id)

        # Bull rebuttal
        print("\n  BULL — Rebuttal...")
        bull_reb = await loop.run_in_executor(
            _executor,
            lambda: debate_rebuttal(
                ticker, "bull", research_reports, bear_open.content, config=config,
                token_callback=make_token_cb("debate", "BULL Rebuttal"),
            ),
        )
        debate_transcript.append(bull_reb.to_dict())
        await events.manager.broadcast({
            "type": events.EVT_DEBATE_ARGUMENT,
            "analysis_id": analysis_id,
            "ticker": ticker,
            "argument": bull_reb.to_dict(),
        })

        _check_cancel(analysis_id)

        # Bear rebuttal
        print("\n  BEAR — Rebuttal...")
        bear_reb = await loop.run_in_executor(
            _executor,
            lambda: debate_rebuttal(
                ticker, "bear", research_reports, bull_reb.content, config=config,
                token_callback=make_token_cb("debate", "BEAR Rebuttal"),
            ),
        )
        debate_transcript.append(bear_reb.to_dict())
        await events.manager.broadcast({
            "type": events.EVT_DEBATE_ARGUMENT,
            "analysis_id": analysis_id,
            "ticker": ticker,
            "argument": bear_reb.to_dict(),
        })

        _check_cancel(analysis_id)

        # Closings
        print("\n  BULL — Closing...")
        bull_close = await loop.run_in_executor(
            _executor,
            lambda: debate_closing(
                ticker, "bull", config=config,
                token_callback=make_token_cb("debate", "BULL Closing"),
            ),
        )
        debate_transcript.append(bull_close.to_dict())
        await events.manager.broadcast({
            "type": events.EVT_DEBATE_ARGUMENT,
            "analysis_id": analysis_id,
            "ticker": ticker,
            "argument": bull_close.to_dict(),
        })

        _check_cancel(analysis_id)

        print("\n  BEAR — Closing...")
        bear_close = await loop.run_in_executor(
            _executor,
            lambda: debate_closing(
                ticker, "bear", config=config,
                token_callback=make_token_cb("debate", "BEAR Closing"),
            ),
        )
        debate_transcript.append(bear_close.to_dict())
        await events.manager.broadcast({
            "type": events.EVT_DEBATE_ARGUMENT,
            "analysis_id": analysis_id,
            "ticker": ticker,
            "argument": bear_close.to_dict(),
        })

        # ── Step 5: Judge verdict ──
        _check_cancel(analysis_id)
        print(f"\n[Step 5] Judge evaluating debate...")

        verdict = await loop.run_in_executor(
            _executor,
            lambda: judge_debate(
                ticker, research_reports, debate_transcript, config=config,
                token_callback=make_token_cb("verdict", "Judge"),
            ),
        )
        verdict_dict = verdict.to_dict()

        await events.manager.broadcast({
            "type": events.EVT_VERDICT,
            "analysis_id": analysis_id,
            "ticker": ticker,
            "verdict": verdict_dict,
        })

        # ── Step 6: Save to DB ──
        if analysis:
            analysis.status = "done"
            analysis.final_decision = verdict_dict.get("final_decision")
            analysis.confidence_score = verdict_dict.get("confidence_score")
            analysis.confidence_label = verdict_dict.get("confidence_label")
            analysis.factors = json.dumps(factors)
            analysis.research_reports = json.dumps(research_reports)
            analysis.debate_transcript = json.dumps(debate_transcript)
            analysis.verdict = json.dumps(verdict_dict)
            db.commit()

        await events.manager.broadcast({
            "type": events.EVT_ANALYSIS_COMPLETE,
            "analysis_id": analysis_id,
            "ticker": ticker,
            "verdict": verdict_dict,
        })

        # ── Step 7: Auto-execute ──
        if auto_execute and verdict_dict.get("final_decision") != "HOLD":
            try:
                from pipeline.execution_pipeline import execute_verdict
                await execute_verdict(verdict_dict, ticker, analysis_id, loop=loop)
            except Exception as e:
                print(f"[Pipeline] Auto-execute error: {e}")

        print(f"\n{'='*60}")
        print(f"  VERDICT: {verdict_dict.get('final_decision')} "
              f"(confidence: {verdict_dict.get('confidence_label')})")
        print(f"{'='*60}\n")

        return verdict_dict

    except AnalysisCancelled:
        print(f"\n[Pipeline] Analysis {analysis_id} CANCELLED by user")
        db2 = SessionLocal()
        try:
            a2 = db2.query(Analysis).filter(Analysis.id == analysis_id).first()
            if a2:
                a2.status = "cancelled"
                db2.commit()
        finally:
            db2.close()

        await events.manager.broadcast({
            "type": events.EVT_ANALYSIS_ERROR,
            "analysis_id": analysis_id,
            "ticker": ticker,
            "error": "Analysis cancelled by user",
            "cancelled": True,
        })
        return {"final_decision": "CANCELLED", "confidence_score": 0}

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[Pipeline] error: {e}\n{tb}")

        db2 = SessionLocal()
        try:
            a2 = db2.query(Analysis).filter(Analysis.id == analysis_id).first()
            if a2:
                a2.status = "failed"
                db2.commit()
        finally:
            db2.close()

        await events.manager.broadcast({
            "type": events.EVT_ANALYSIS_ERROR,
            "analysis_id": analysis_id,
            "ticker": ticker,
            "error": str(e),
        })
        raise
    finally:
        _cancel_flags.pop(analysis_id, None)
        db.close()
