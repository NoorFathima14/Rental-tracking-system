"""
Usage Logging module.

ASSUMPTIONS (documented so they're easy to explain):
- No true per-day sensor logs exist (that layer was intentionally dropped
  for scope). Engine Hours/Day and Idle Hours/Day on each booking are a
  DAILY AVERAGE for that rental. So total runtime/idle hours for a booking
  = per-day value * Rental Days (the PLANNED duration).
- Fuel is estimated using fixed per-type burn rates (same ones used by the
  synthetic data generator), not a logged reading.
- No idle "ratio" or "utilization %" is computed - engine + idle hours do
  not reliably sum to a fixed daily capacity, so any ratio would be
  misleading (documented decision from earlier dashboard work).
- No fuel cost - only litres. Cost conversion adds no real insight here.

Filters (site_id, equipment_type, date range) apply BEFORE any grouping,
and are shared across all four breakdown views (Equipment / Site /
Operator / Time Period).
"""

import pandas as pd
from datetime import date
from sqlalchemy.orm import Session

from .db_models import Booking
from .dashboard_metrics import bookings_to_dataframe as dm_bookings_to_dataframe, compute_equipment_status

FUEL_RATES = {
    "Excavator": {"active_lph": 18, "idle_lph": 4},
    "Crane":     {"active_lph": 12, "idle_lph": 2},
    "Bulldozer": {"active_lph": 22, "idle_lph": 5},
    "Grader":    {"active_lph": 15, "idle_lph": 3},
}


def bookings_to_dataframe(db: Session) -> pd.DataFrame:
    rows = db.query(Booking).all()
    data = [{
        "booking_id": b.booking_id,
        "equipment_id": b.equipment_id,
        "type": b.type,
        "site_id": b.site_id,
        "check_in_date": b.check_in_date,
        "check_out_date": b.check_out_date,
        "engine_hours_per_day": b.engine_hours_per_day,
        "idle_hours_per_day": b.idle_hours_per_day,
        "rental_days": b.rental_days,
        "operator_id": b.last_operator_id,
    } for b in rows]
    df = pd.DataFrame(data)
    if not df.empty:
        df["check_in_date"] = pd.to_datetime(df["check_in_date"])
        df["check_out_date"] = pd.to_datetime(df["check_out_date"])
    return df


def compute_booking_usage(df: pd.DataFrame) -> pd.DataFrame:
    """Adds derived usage columns to each booking row."""
    df = df.copy()

    df["runtime_hours"] = (df["engine_hours_per_day"].fillna(0) * df["rental_days"].fillna(0)).round(1)
    df["idle_hours_total"] = (df["idle_hours_per_day"].fillna(0) * df["rental_days"].fillna(0)).round(1)

    def fuel_for_row(row):
        rates = FUEL_RATES.get(row["type"])
        if rates is None or pd.isnull(row["engine_hours_per_day"]) or pd.isnull(row["rental_days"]):
            return None
        active_fuel = row["engine_hours_per_day"] * rates["active_lph"] * row["rental_days"]
        idle_fuel = (row["idle_hours_per_day"] or 0) * rates["idle_lph"] * row["rental_days"]
        return round(active_fuel + idle_fuel, 1)

    df["estimated_fuel_litres"] = df.apply(fuel_for_row, axis=1)

    def returned_late(row):
        if pd.isnull(row["check_out_date"]) or pd.isnull(row["rental_days"]):
            return None
        planned_end = row["check_in_date"] + pd.Timedelta(days=int(row["rental_days"]))
        return bool(row["check_out_date"] > planned_end)

    df["returned_late"] = df.apply(returned_late, axis=1)
    df["returned_late_int"] = df["returned_late"].apply(lambda x: 1 if x is True else 0)
    return df


def filter_bookings(
    df: pd.DataFrame,
    site_id: str = None,
    equipment_type: str = None,
    start_date: date = None,
    end_date: date = None,
) -> pd.DataFrame:
    """
    Filters by site, equipment type, and a check-in-date window.
    Time period filter applies to Check-In Date ("bookings that started
    within this window") - simple and explainable, avoids partial-overlap logic.
    """
    filtered = df.copy()

    if site_id:
        filtered = filtered[filtered["site_id"] == site_id]
    if equipment_type:
        filtered = filtered[filtered["type"] == equipment_type]
    if start_date:
        filtered = filtered[filtered["check_in_date"] >= pd.Timestamp(start_date)]
    if end_date:
        filtered = filtered[filtered["check_in_date"] <= pd.Timestamp(end_date)]

    return filtered


# ---------------------------------------------------------------------------
# Breakdown views
# ---------------------------------------------------------------------------

def breakdown_by_equipment(df: pd.DataFrame, db: Session) -> list:
    """One row per equipment_id. Includes CURRENT status, computed from the
    full (unfiltered) booking history, since 'what is it doing right now'
    is a live fact independent of whatever date range is being viewed."""
    if df.empty:
        return []

    grouped = (
        df.groupby(["equipment_id", "type"], dropna=False)
        .agg(
            bookings=("booking_id", "count"),
            total_runtime_hours=("runtime_hours", "sum"),
            total_idle_hours=("idle_hours_total", "sum"),
            total_fuel_litres=("estimated_fuel_litres", "sum"),
            late_returns=("returned_late_int", "sum"),
        )
        .round(1)
        .reset_index()
    )

    # Merge in live status from the FULL unfiltered dataset
    full_df = dm_bookings_to_dataframe(db)
    status_df = compute_equipment_status(full_df)
    status_lookup = status_df.set_index("equipment_id")["status"].to_dict()
    grouped["current_status"] = grouped["equipment_id"].map(status_lookup)

    return grouped.to_dict(orient="records")


def breakdown_by_site(df: pd.DataFrame) -> list:
    if df.empty:
        return []

    df = df.copy()
    df["site_id"] = df["site_id"].fillna("Unassigned")

    grouped = (
        df.groupby("site_id")   # no dropna needed now - no NaN left in the column
        .agg(
            bookings=("booking_id", "count"),
            total_runtime_hours=("runtime_hours", "sum"),
            total_idle_hours=("idle_hours_total", "sum"),
            total_fuel_litres=("estimated_fuel_litres", "sum"),
            distinct_equipment=("equipment_id", "nunique"),
        )
        .round(1)
        .reset_index()
    )
    return grouped.to_dict(orient="records")


def breakdown_by_operator(df: pd.DataFrame) -> list:
    if df.empty:
        return []

    df = df.copy()
    df["operator_id"] = df["operator_id"].fillna("Unassigned")

    grouped = (
        df.groupby("operator_id")
        .agg(
            bookings=("booking_id", "count"),
            total_runtime_hours=("runtime_hours", "sum"),
            total_idle_hours=("idle_hours_total", "sum"),
            late_returns=("returned_late_int", "sum"),
        )
        .round(1)
        .reset_index()
    )
    grouped["late_return_rate_pct"] = (
        (grouped["late_returns"] / grouped["bookings"]) * 100
    ).round(1)

    return grouped.to_dict(orient="records")


def breakdown_by_time_period(df: pd.DataFrame, granularity: str = "month") -> list:
    """
    One row per time bucket (week or month), based on Check-In Date.
    granularity: 'week' or 'month'
    """
    if df.empty:
        return []

    df = df.copy()
    if granularity == "week":
        df["period"] = df["check_in_date"].dt.to_period("W").apply(lambda p: str(p.start_time.date()))
    else:  # month
        df["period"] = df["check_in_date"].dt.to_period("M").apply(lambda p: str(p))

    grouped = (
        df.groupby("period", dropna=False)
        .agg(
            bookings=("booking_id", "count"),
            total_runtime_hours=("runtime_hours", "sum"),
            total_idle_hours=("idle_hours_total", "sum"),
            total_fuel_litres=("estimated_fuel_litres", "sum"),
        )
        .round(1)
        .reset_index()
        .sort_values("period")
    )
    return grouped.to_dict(orient="records")