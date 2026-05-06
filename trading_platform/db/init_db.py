"""
db/init_db.py — Create all tables on startup.
"""
from core.database import engine, Base
from core import models  # noqa: F401  — import so all models register with Base


def init_database():
    Base.metadata.create_all(bind=engine)
    print("[DB] All tables created/verified.")
