"""
backend/app/dashboard_metrics.py

Layer 1 (Fleet Pulse) calculations — pure functions, no FastAPI/DB coupling
beyond reading the Booking table. Import and call these from a route later.

ASSUMPTION (flagging clearly): our schema has Check-In Date (equipment goes
out) and Check-Out Date (planned/expected return) but no separate "actual
returned" field. So live status is inferred:
  - ACTIVE   : today is within [check_in, check_out]
  - OVERDUE  : today is past check_out, but only within OVERDUE_GRACE_DAYS
               (older completed bookings are assumed returned, not overdue forever)
  - AVAILABLE: no current booking covers today for that equipment
Tune OVERDUE_GRACE_DAYS below once you add a real "returned" flag later.
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
    Picks the most recent booking whose check_in_date <= today (i.e. the one
    that has actually started), then classifies it.

    NOTE: no grace window on overdue. Once a booking's check_out_date has
    passed, this equipment stays OVERDUE indefinitely (days_overdue keeps
    growing) rather than assuming it was returned. This is intentional so the
    overdue alerts/escalation feature can consume days_overdue directly.
    """
    started = bookings[bookings["check_in_date"] <= today]

    if started.empty:
        # This equipment has no booking that has started yet (only future bookings, or none at all)
        return {"status": "AVAILABLE", "days_overdue": 0, "current_booking": None}

    # Most recent booking that has started
    latest = started.sort_values("check_in_date", ascending=False).iloc[0]
    checkout = latest["check_out_date"]

    if pd.isnull(checkout):
        # No expected return date logged at all -> can't confirm status, flag as anomaly-worthy
        return {"status": "UNKNOWN_NO_CHECKOUT", "days_overdue": 0, "current_booking": latest}

    if today <= checkout:
        return {"status": "ACTIVE", "days_overdue": 0, "current_booking": latest}

    # Past checkout date -> stays OVERDUE, no grace window, no auto-reset
    days_late = (today - checkout).days
    return {"status": "OVERDUE", "days_overdue": days_late, "current_booking": latest}

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
            # total_hrs = (engine_hrs or 0) + (idle_hrs or 0)
            # utilization_pct = round((engine_hrs / total_hrs) * 100, 1) if total_hrs > 0 else 0.0
            site_id = booking["site_id"]
            operator_id = booking["last_operator_id"]
            eq_type = booking["type"]
            check_out_date = booking["check_out_date"]
        else:
            engine_hrs = idle_hrs = utilization_pct = None
            site_id = operator_id = check_out_date = None
            eq_type = group["type"].iloc[0]  # type doesn't change across a machine's bookings

        results.append({
            "equipment_id": equipment_id,
            "type": eq_type,
            "status": info["status"],
            "site_id": site_id,
            "operator_id": operator_id,
            "engine_hours_per_day": engine_hrs,
            "idle_hours_per_day": idle_hrs,
            # "utilization_pct": utilization_pct,
            "expected_checkout_date": check_out_date,
            "days_overdue": info["days_overdue"],
        })

    return pd.DataFrame(results)

IDLE_HOURS_THRESHOLD = 6.0   # flag as "idle now" if idle_hours_per_day exceeds this (tune per your data's spread)

def compute_fleet_pulse(status_df: pd.DataFrame) -> dict:
    """
    Layer 1 summary cards: Total | Active | Idle now | Overdue.
    (Avg utilization % removed for now - engine+idle hours don't reliably sum
    to a fixed daily capacity, and Crane can be 0 engine hrs while still fully
    utilized, so a % figure was misleading. Idle flag now uses an absolute
    idle-hours threshold instead of a ratio.)
    """
    total_equipment = len(status_df)
    active_df = status_df[status_df["status"] == "ACTIVE"]
    currently_active = len(active_df)

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

        print("\n=== Sample equipment statuses ===")
        print(status_df.head(10).to_string(index=False))
    finally:
        db.close()