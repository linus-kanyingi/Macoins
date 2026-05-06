"""
core/config.py — Loads settings from .env using python-dotenv.
"""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv(override=True)


@dataclass
class Settings:
    # Alpaca
    ALPACA_API_KEY: str = field(default_factory=lambda: os.getenv("ALPACA_API_KEY", ""))
    ALPACA_SECRET_KEY: str = field(default_factory=lambda: os.getenv("ALPACA_SECRET_KEY", ""))
    ALPACA_BASE_URL: str = field(default_factory=lambda: os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets/v2"))
    ALPACA_DATA_URL: str = field(default_factory=lambda: os.getenv("ALPACA_DATA_URL", "https://data.alpaca.markets/v2"))

    # LLM APIs
    ANTHROPIC_API_KEY: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    OPENAI_API_KEY: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    GEMINI_API_KEY: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    DEEPSEEK_API_KEY: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    GROK_API_KEY: str = field(default_factory=lambda: os.getenv("GROK_API_KEY", ""))

    # Ollama (default local LLM)
    OLLAMA_BASE_URL: str = field(default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
    OLLAMA_MODEL: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "gemma4:e2b"))

    # Database
    DB_PATH: str = field(default_factory=lambda: os.getenv("DB_PATH", "db/trading.db"))

    # Risk management
    MAX_POSITION_PCT: float = field(default_factory=lambda: float(os.getenv("MAX_POSITION_PCT", "0.05")))
    MAX_OPEN_POSITIONS: int = field(default_factory=lambda: int(os.getenv("MAX_OPEN_POSITIONS", "10")))
    STOP_LOSS_PCT: float = field(default_factory=lambda: float(os.getenv("STOP_LOSS_PCT", "0.10")))
    MIN_CONFIDENCE_TO_EXECUTE: float = field(default_factory=lambda: float(os.getenv("MIN_CONFIDENCE_TO_EXECUTE", "0.55")))

    # Server
    HOST: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    PORT: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))


settings = Settings()
