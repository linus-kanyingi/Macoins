"""pipeline/analysis_pipeline.py — Async orchestrator: market data → debate → judges → verdict."""
from __future__ import annotations
import asyncio
import json
import traceback
from concurrent.futures import ThreadPoolExecutor
from agents.trading.market_data_agent import market_data_agent
from core import events
from core.database import SessionLocal
from core.models import Analysis

_executor = ThreadPoolExecutor(max_workers=4)


async def run_analysis(
    ticker: str,
    analysis_id: int,
    rounds: int = 1,
    include_hold: bool = False,
    skip_judges: bool = False,
    skip_factcheck: bool = False,
    auto_execute: bool = False,
    loop=None,
) -> dict:
    loop = loop or asyncio.get_event_loop()
    db   = SessionLocal()

    try:
        # Mark running
        analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        if analysis:
            analysis.status = "running"
            db.commit()

        # 1. Build scenario
        scenario = await loop.run_in_executor(_executor, lambda: market_data_agent.build_scenario(ticker))

        await events.manager.broadcast({
            "type": "analysis_started",
            "analysis_id": analysis_id,
            "ticker": ticker,
            "price": scenario.current_price,
        })

        # 2. Run debate
        transcript_turns = []

        def _run_debate():
            from agents.debate.orchestrator import DebateOrchestrator
            orch = DebateOrchestrator(scenario, num_rounds=rounds, include_hold=include_hold)
            try:
                return orch.run()
            except TypeError:
                return orch.run(topic=scenario.to_debate_topic())

        transcript = await loop.run_in_executor(_executor, _run_debate)

        # Broadcast turns
        if hasattr(transcript, 'turns'):
            for turn in transcript.turns:
                await events.manager.broadcast({
                    "type": events.EVT_DEBATE_TURN,
                    "analysis_id": analysis_id,
                    "speaker":    getattr(turn, 'speaker', ''),
                    "turn_type":  getattr(turn, 'turn_type', ''),
                    "round_num":  getattr(turn, 'round_num', 0),
                    "content":    getattr(turn, 'content', ''),
                })

        # 3. Factcheck
        factcheck_results = []
        if not skip_factcheck:
            def _run_fc():
                from agents.factcheck.factcheck import FactChecker
                return FactChecker().check(transcript, scenario)
            try:
                factcheck_results = await loop.run_in_executor(_executor, _run_fc)
            except Exception as e:
                print(f"[Pipeline] factcheck error: {e}")

        # 4. Judges
        judge_scores = []
        if not skip_judges:
            def _run_judges():
                from agents.judges.judge_panel import run_judge_ensemble
                txt = ""
                if hasattr(transcript, 'turns'):
                    txt = "\n".join(f"[{t.speaker}] {t.content}" for t in transcript.turns
                                    if hasattr(t, 'speaker'))
                elif isinstance(transcript, str):
                    txt = transcript
                return run_judge_ensemble(txt)
            try:
                judge_scores = await loop.run_in_executor(_executor, _run_judges)
            except Exception as e:
                print(f"[Pipeline] judge error: {e}")

        # 5. Aggregate
        def _aggregate():
            from agents.aggregator.aggregator import aggregate_results
            return aggregate_results(transcript, judge_scores, factcheck_results, scenario)

        verdict_obj  = await loop.run_in_executor(_executor, _aggregate)
        verdict_dict = verdict_obj.to_dict() if hasattr(verdict_obj, 'to_dict') else {}

        # 6. Save to DB
        if analysis:
            turns_data = []
            if hasattr(transcript, 'turns'):
                for t in transcript.turns:
                    turns_data.append({
                        "speaker":   getattr(t, 'speaker', ''),
                        "turn_type": getattr(t, 'turn_type', ''),
                        "round_num": getattr(t, 'round_num', 0),
                        "content":   getattr(t, 'content', ''),
                    })
            analysis.status           = "done"
            analysis.final_decision   = verdict_dict.get("final_decision")
            analysis.confidence_score = verdict_dict.get("confidence_score")
            analysis.confidence_label = verdict_dict.get("confidence_label")
            analysis.debate_transcript = json.dumps(turns_data)
            analysis.verdict          = json.dumps(verdict_dict)
            analysis.judge_scores     = json.dumps([
                s.to_dict() if hasattr(s, 'to_dict') else {} for s in judge_scores
            ])
            db.commit()

        # 7. Broadcast complete
        await events.manager.broadcast({
            "type":        events.EVT_ANALYSIS_COMPLETE,
            "analysis_id": analysis_id,
            "ticker":      ticker,
            "verdict":     verdict_dict,
        })

        # 8. Auto-execute
        if auto_execute:
            from pipeline.execution_pipeline import execute_verdict
            await execute_verdict(verdict_dict, ticker, analysis_id, loop=loop)

        return verdict_dict

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
            "type":        events.EVT_ANALYSIS_ERROR,
            "analysis_id": analysis_id,
            "ticker":      ticker,
            "error":       str(e),
        })
        raise
    finally:
        db.close()
