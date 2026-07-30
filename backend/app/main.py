from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import inspect
import pandas as pd
from pathlib import Path

from app.config import settings
from app.models import HealthResponse
from app.database import engine, get_db, Base
from app.db_models import Booking

app = FastAPI(title="Smart Rental Tracking API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CSV_PATH = Path("dataset/bookings.csv")


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)  # creates bookings.db table if it doesn't exist
    _load_csv_if_empty()


def _load_csv_if_empty():
    """Loads bookings.csv into SQLite only if the table is currently empty,
    so re-running the container doesn't duplicate rows every restart."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        existing_count = db.query(Booking).count()
        if existing_count > 0:
            print(f"DB already has {existing_count} bookings — skipping CSV load")
            return

        if not CSV_PATH.exists():
            print(f"WARNING: {CSV_PATH} not found, DB stays empty")
            return

        df = pd.read_csv(CSV_PATH, parse_dates=["Check-In Date", "Check-Out Date"])

        for _, row in df.iterrows():
            booking = Booking(
                booking_id=row.get("booking_id"),
                equipment_id=row["Equipment ID"],
                type=row["Type"],
                site_id=None if pd.isnull(row["Site ID"]) else row["Site ID"],
                check_in_date=None if pd.isnull(row["Check-In Date"]) else row["Check-In Date"].date(),
                check_out_date=None if pd.isnull(row["Check-Out Date"]) else row["Check-Out Date"].date(),
                engine_hours_per_day=row["Engine Hours/Day"],
                idle_hours_per_day=row["Idle Hours/Day"],
                rental_days=None if pd.isnull(row["Rental Days"]) else int(row["Rental Days"]),
                last_operator_id=None if pd.isnull(row["Last Operator ID"]) else row["Last Operator ID"],
            )
            db.add(booking)

        db.commit()
        print(f"Loaded {len(df)} bookings into SQLite")
    finally:
        db.close()


@app.get("/api/health", response_model=HealthResponse)
async def health(db: Session = Depends(get_db)):
    return HealthResponse(status="ok", rows_loaded=db.query(Booking).count())


@app.get("/api/bookings")
async def get_bookings(
    site_id: str | None = None,
    equipment_type: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(Booking)
    if site_id:
        query = query.filter(Booking.site_id == site_id)
    if equipment_type:
        query = query.filter(Booking.type == equipment_type)
    return [b.__dict__ for b in query.all()]


@app.get("/api/bookings/{equipment_id}")
async def get_equipment_bookings(equipment_id: str, db: Session = Depends(get_db)):
    results = db.query(Booking).filter(Booking.equipment_id == equipment_id).all()
    if not results:
        raise HTTPException(status_code=404, detail="Equipment ID not found")
    return [b.__dict__ for b in results]

