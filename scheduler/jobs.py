"""scheduler/jobs.py — APScheduler job functions (top-level for serialization)."""
from __future__ import annotations
import asyncio


def job_sync_portfolio():
    """Sync portfolio from Alpaca — runs every 30 s."""
    try:
        from broker.portfolio_tracker import sync_portfolio
        loop = asyncio.get_event_loop()
        sync_portfolio(loop=loop)
    except RuntimeError:
        try:
            from broker.portfolio_tracker import sync_portfolio
            loop = asyncio.new_event_loop()
            sync_portfolio(loop=loop)
        except Exception as e:
            print(f"[Scheduler] portfolio sync error: {e}")
    except Exception as e:
        print(f"[Scheduler] portfolio sync error: {e}")


def job_sync_orders():
    """Sync open order statuses — runs every 60 s."""
    try:
        from broker.order_manager import sync_open_orders
        sync_open_orders()
    except Exception as e:
        print(f"[Scheduler] order sync error: {e}")


def job_scheduled_analysis(ticker: str, rounds: int = 1, auto_execute: bool = False):
    """Run a scheduled analysis on a ticker (cron-based)."""
    from pipeline.analysis_pipeline import run_analysis
    from core.database import SessionLocal
    from core.models import Analysis

    db = SessionLocal()
    try:
        analysis = Analysis(ticker=ticker.upper(), status="queued")
        db.add(analysis)
        db.commit()
        analysis_id = analysis.id
    finally:
        db.close()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_analysis(
            ticker=ticker.upper(), analysis_id=analysis_id,
            rounds=rounds, auto_execute=auto_execute, loop=loop,
        ))
    except Exception as e:
        print(f"[Scheduler] analysis job error: {e}")
    finally:
        loop.close()
