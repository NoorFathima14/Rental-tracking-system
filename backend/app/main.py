from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import pandas as pd
from pathlib import Path
from datetime import date
from pydantic import BaseModel
import json

from .config import settings
from .models import HealthResponse
from .database import engine, get_db, Base
from .db_models import Booking
from .dashboard_metrics import bookings_to_dataframe, compute_equipment_status, compute_fleet_pulse
from .checkin_checkout import check_in, check_out, build_fleet_by_type

app = FastAPI(title="Smart Rental Tracking API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CSV_PATH = Path("dataset/bookings.csv")
FLEET_BY_TYPE = build_fleet_by_type()


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    _load_csv_if_empty()


def _load_csv_if_empty():
    from .database import SessionLocal

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


@app.get("/api/dashboard/pulse")
async def dashboard_pulse(db: Session = Depends(get_db)):
    df = bookings_to_dataframe(db)
    status_df = compute_equipment_status(df)
    pulse = compute_fleet_pulse(status_df)
    equipment_status = json.loads(status_df.to_json(orient="records", date_format="iso"))

    return {
        "pulse": pulse,
        "equipment_status": equipment_status,
    }


class CheckInRequest(BaseModel):
    equipment_type: str
    site_id: str
    check_in_date: date
    rental_days: int
    operator_id: str


class CheckOutRequest(BaseModel):
    operator_id: str
    equipment_type: str
    site_id: str
    check_in_date: date


@app.post("/api/checkin")
async def api_check_in(req: CheckInRequest, db: Session = Depends(get_db)):
    result = check_in(
        db,
        equipment_type=req.equipment_type,
        site_id=req.site_id,
        check_in_date=req.check_in_date,
        rental_days=req.rental_days,
        operator_id=req.operator_id,
        fleet_by_type=FLEET_BY_TYPE,
    )
    if not result["success"]:
        raise HTTPException(status_code=409, detail=result["message"])
    return result


@app.post("/api/checkout")
async def api_check_out(req: CheckOutRequest, db: Session = Depends(get_db)):
    result = check_out(
        db,
        operator_id=req.operator_id,
        equipment_type=req.equipment_type,
        site_id=req.site_id,
        check_in_date=req.check_in_date,
    )
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return result

from .usage_logging import (
    bookings_to_dataframe as usage_bookings_to_dataframe,
    compute_booking_usage,
    filter_bookings,
    breakdown_by_equipment,
    breakdown_by_site,
    breakdown_by_operator,
    breakdown_by_time_period,
)


@app.get("/api/usage")
async def usage(
    view: str = "equipment",       # equipment | site | operator | time
    granularity: str = "month",    # week | month (only used when view=time)
    site_id: str | None = None,
    equipment_type: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
):
    df = usage_bookings_to_dataframe(db)
    df = compute_booking_usage(df)
    df = filter_bookings(df, site_id=site_id, equipment_type=equipment_type, start_date=start_date, end_date=end_date)

    if view == "equipment":
        rows = breakdown_by_equipment(df, db)
    elif view == "site":
        rows = breakdown_by_site(df)
    elif view == "operator":
        rows = breakdown_by_operator(df)
    elif view == "time":
        rows = breakdown_by_time_period(df, granularity=granularity)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown view: {view}")

    return {"view": view, "granularity": granularity if view == "time" else None, "rows": rows}