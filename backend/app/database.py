"""
SQLite connection setup. DB file lives in the mounted dataset/ folder so it
persists across container restarts (same volume as bookings.csv).
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = "sqlite:///dataset/rental.db"

# check_same_thread=False needed because FastAPI can use different threads per request
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency — yields a session, closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()