"""main.py — Entry point for Agentic Trading Platform."""
import os
import sys
import argparse

# Unset SSLKEYLOGFILE to prevent permission errors on Windows when python's ssl module initializes
os.environ.pop("SSLKEYLOGFILE", None)

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn
from api.app_factory import create_app
from core.config import settings

app = create_app()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agentic Trading Platform")
    parser.add_argument("--host",   default=settings.HOST)
    parser.add_argument("--port",   type=int, default=settings.PORT)
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev only)")
    args = parser.parse_args()

    print(f"""
+--------------------------------------------------+
|       Agentic Trading Platform  v2.0              |
|       Multi-Agent Financial Analysis              |
+--------------------------------------------------+
|  UI  -> http://localhost:{args.port:<23}|
|  API -> http://localhost:{args.port}/docs{' '*19}|
|  Mode:  PAPER TRADING (no real money)            |
+--------------------------------------------------+
""")

    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        ws_ping_interval=20,
        ws_ping_timeout=20,
    )
