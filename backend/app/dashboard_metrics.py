"""
backend/app/dashboard_metrics.py

Layer 1 (Fleet Pulse) calculations — pure functions, no FastAPI/DB coupling
beyond reading the Booking table.

SCHEMA SEMANTICS (matches the corrected data generator):
  - Check-In Date  : equipment goes out (known upfront)
  - Rental Days    : PLANNED/agreed rental duration (known upfront)
  - Check-Out Date : ACTUAL return date. NULL means "not yet returned" -
                      this is the currently open/live booking for that equipment.

Live status is derived as follows, per equipment:
  - If the equipment's most recent started booking has a non-null
    Check-Out Date -> it has already been returned -> AVAILABLE.
  - If it has a NULL Check-Out Date -> it's the currently open booking:
        planned_checkout = check_in_date + rental_days
        today <= planned_checkout -> ACTIVE
        today >  planned_checkout -> OVERDUE (days_overdue = today - planned_checkout)
  - No booking has started yet for this equipment -> AVAILABLE.

No grace window: once OVERDUE, it stays OVERDUE and days_overdue keeps
growing until an actual Check-Out Date is recorded (i.e. real check-out
happens through the check-in/check-out system).
"""

import pandas as pd
from datetime import date, timedelta
from sqlalchemy.orm import Session

from .db_models import Booking


def bookings_to_dataframe(db: Session) -> pd.DataFrame:
    """Pulls all bookings from the DB into a DataFrame for vectorized computation."""
    rows = db.query(Booking).all()
    data = [{
        "equipment_id": b.equipment_id,
        "type": b.type,
        "site_id": b.site_id,
        "check_in_date": b.check_in_date,
        "check_out_date": b.check_out_date,
        "engine_hours_per_day": b.engine_hours_per_day,
        "idle_hours_per_day": b.idle_hours_per_day,
        "rental_days": b.rental_days,
        "last_operator_id": b.last_operator_id,
    } for b in rows]
    return pd.DataFrame(data)


def _status_for_equipment(bookings: pd.DataFrame, today: date) -> dict:
    """
    Given all bookings for ONE equipment_id, determine its live status as of `today`.
    """
    started = bookings[bookings["check_in_date"] <= today]

    if started.empty:
        # No booking has started yet for this equipment (only future bookings, or none at all)
        return {"status": "AVAILABLE", "days_overdue": 0, "current_booking": None}

    # Most recent booking that has started
    latest = started.sort_values("check_in_date", ascending=False).iloc[0]
    checkout = latest["check_out_date"]

    if pd.notnull(checkout):
        # Already actually returned -> equipment is free, regardless of when
        if checkout <= today:
            return {"status": "AVAILABLE", "days_overdue": 0, "current_booking": None}
        # Actual checkout date is in the future relative to "today" - shouldn't
        # happen with clean data, but guard against it rather than crash/mislabel.
        return {"status": "UNKNOWN_FUTURE_CHECKOUT", "days_overdue": 0, "current_booking": latest}

    # Check-Out Date is NULL -> this is the currently open booking
    rental_days = latest["rental_days"]
    check_in_date = latest["check_in_date"]

    if pd.isnull(rental_days) or rental_days <= 0:
        # Can't determine a planned end date -> flag rather than guess
        return {"status": "UNKNOWN_NO_RENTAL_DAYS", "days_overdue": 0, "current_booking": latest}

    planned_checkout = check_in_date + timedelta(days=int(rental_days))

    if today <= planned_checkout:
        return {"status": "ACTIVE", "days_overdue": 0, "current_booking": latest,
                "planned_checkout": planned_checkout}

    days_late = (today - planned_checkout).days
    return {"status": "OVERDUE", "days_overdue": days_late, "current_booking": latest,
            "planned_checkout": planned_checkout}


def compute_equipment_status(df: pd.DataFrame, today: date = None) -> pd.DataFrame:
    """
    Returns one row per equipment_id with its live status + relevant fields.
    This is the core "what is every machine doing right now" table.
    """
    if today is None:
        today = date.today()

    results = []
    for equipment_id, group in df.groupby("equipment_id"):
        info = _status_for_equipment(group, today)
        booking = info["current_booking"]

        if booking is not None:
            engine_hrs = booking["engine_hours_per_day"]
            idle_hrs = booking["idle_hours_per_day"]
            site_id = booking["site_id"]
            operator_id = booking["last_operator_id"]
            eq_type = booking["type"]
            planned_checkout_date = info.get("planned_checkout")
        else:
            engine_hrs = idle_hrs = None
            site_id = operator_id = planned_checkout_date = None
            eq_type = group["type"].iloc[0]  # type doesn't change across a machine's bookings

        results.append({
            "equipment_id": equipment_id,
            "type": eq_type,
            "status": info["status"],
            "site_id": site_id,
            "operator_id": operator_id,
            "engine_hours_per_day": engine_hrs,
            "idle_hours_per_day": idle_hrs,
            "expected_checkout_date": planned_checkout_date,
            "days_overdue": info["days_overdue"],
        })

    return pd.DataFrame(results)


IDLE_HOURS_THRESHOLD = 6.0   # flag as "idle now" if idle_hours_per_day exceeds this


def compute_fleet_pulse(status_df: pd.DataFrame) -> dict:
    """
    Layer 1 summary cards: Total | Active | Available | Idle now | Overdue.
    """
    total_equipment = len(status_df)
    active_df = status_df[status_df["status"] == "ACTIVE"]
    currently_active = len(active_df)

    available_df = status_df[status_df["status"] == "AVAILABLE"]
    available = len(available_df)
    available_list = available_df[["equipment_id", "type"]].to_dict(orient="records")

    overdue_df = status_df[status_df["status"] == "OVERDUE"]
    overdue = len(overdue_df)
    overdue_list = overdue_df[["equipment_id", "type", "site_id", "days_overdue"]].to_dict(orient="records")

    idle_now = 0
    idle_list = []
    if not active_df.empty:
        idle_mask = active_df["idle_hours_per_day"].fillna(0) > IDLE_HOURS_THRESHOLD
        idle_now = int(idle_mask.sum())
        idle_list = active_df[idle_mask][["equipment_id", "type", "site_id", "idle_hours_per_day"]].to_dict(orient="records")

    return {
        "total_equipment": total_equipment,
        "currently_active": currently_active,
        "available": available,
        "available_list": available_list,
        "idle_now": idle_now,
        "idle_list": idle_list,
        "overdue": overdue,
        "overdue_list": overdue_list,
    }


# ---------------------------------------------------------------------------
# Standalone test — run this file directly to sanity-check the numbers
# before wiring it into a FastAPI route.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from .database import SessionLocal

    db = SessionLocal()
    try:
        df = bookings_to_dataframe(db)
        status_df = compute_equipment_status(df, today=date.today())
        pulse = compute_fleet_pulse(status_df)

        print("=== Fleet Pulse (Layer 1) ===")
        for k, v in pulse.items():
            print(f"{k}: {v}")

        print("\n=== All equipment statuses ===")
        print(status_df.to_string(index=False))
    finally:
        db.close()