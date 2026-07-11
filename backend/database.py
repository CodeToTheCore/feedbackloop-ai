"""
database.py
------------
Sets up the SQLAlchemy engine, session factory, and declarative base.

Dev default: SQLite file (feedbackloop.db) so the app runs with zero setup.
To deploy on Postgres later, just set the DATABASE_URL environment variable, e.g.:

    export DATABASE_URL="postgresql://user:password@host:5432/feedbackloop"

No other code changes are required — SQLAlchemy handles the dialect switch.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./feedbackloop.db")

# SQLite needs this connect_arg when used with FastAPI's threaded request handling.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a DB session per-request and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
