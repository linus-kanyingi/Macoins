"""
core/database.py — SQLAlchemy engine and session setup.
"""
import os
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from core.config import settings

# Ensure the DB directory exists
db_dir = os.path.dirname(os.path.abspath(settings.DB_PATH))
os.makedirs(db_dir, exist_ok=True)

DATABASE_URL = f"sqlite:///{os.path.abspath(settings.DB_PATH)}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

Base = declarative_base()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _run_migrations():
    """Add new columns to existing tables without losing data."""
    inspector = inspect(engine)
    if "trades" in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns("trades")]
        if "source" not in columns:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE trades ADD COLUMN source VARCHAR DEFAULT 'unknown'"
                ))
            print("[DB] Migration: added 'source' column to trades table")


_run_migrations()


def get_session():
    """FastAPI dependency injection generator."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

