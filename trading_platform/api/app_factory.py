"""api/app_factory.py — Creates the FastAPI application with all routes and middleware."""
from __future__ import annotations
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from core.scheduler import scheduler, start_default_jobs
from db.init_db import init_database
from api.routes import ws, trading, market, analysis_routes, expert_routes, llm_routes, scheduler_routes, strategy_chat


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_database()
    start_default_jobs()
    scheduler.start()
    print("[OK] Database initialized | Scheduler started")
    yield
    # Shutdown
    if scheduler.running:
        scheduler.shutdown(wait=False)
    print("Scheduler stopped.")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Agentic Trading Platform",
        description="Multi-Agent Trading Platform — Demonstrating Agentic Behavior",
        version="2.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routers
    app.include_router(ws.router)
    app.include_router(trading.router)
    app.include_router(market.router)
    app.include_router(analysis_routes.router)
    app.include_router(expert_routes.router)
    app.include_router(llm_routes.router)
    app.include_router(scheduler_routes.router)
    app.include_router(strategy_chat.router)

    # Serve frontend as static files
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
    if os.path.exists(frontend_dir):
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

    return app
