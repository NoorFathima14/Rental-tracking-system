"""
Check-in (equipment goes out) and Check-out (equipment returned) logic.

Check-in inputs (5 fields): equipment_type, site_id, check_in_date, rental_days, operator_id
  -> finds an available unit of that type, assigns the most historically-idle
     one, creates a new OPEN booking (Check-Out Date left NULL).

Check-out inputs (4 fields): operator_id, equipment_type, site_id, check_in_date
  -> these four together identify the open booking to close.
  -> Check-Out Date is set to TODAY automatically (the moment of check-out),
     not user-supplied. Rental Days is left as originally planned - it is
     not recalculated from the actual return, since Rental Days represents
     the AGREED duration and comparing it to the actual return is exactly
     what produces the overdue signal elsewhere in the system.
"""

from datetime import date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func

from .db_models import Booking

EQUIPMENT_TYPES = ["Excavator", "Crane", "Bulldozer", "Grader"]
FLEET_SIZE_PER_TYPE = 6  # matches current data_generation.py fleet size


def build_fleet_by_type() -> dict:
    """
    Fixed fleet reference (mirrors data_generation.py's build_fleet()).
    Kept as a constant here so availability checks don't depend on an
    equipment_id already having booking history to be considered part
    of the fleet.
    """
    fleet = {}
    counter = 1001
    for eq_type in EQUIPMENT_TYPES:
        fleet[eq_type] = [f"EQX{counter + i}" for i in range(FLEET_SIZE_PER_TYPE)]
        counter += FLEET_SIZE_PER_TYPE
    return fleet


def get_available_equipment_ids(db: Session, equipment_type: str, fleet_ids: list) -> list:
    """
    An equipment_id is UNAVAILABLE if it has any booking row with
    Check-Out Date IS NULL (checked out, not yet returned).
    """
    checked_out_ids = {
        row.equipment_id
        for row in db.query(Booking.equipment_id)
        .filter(Booking.type == equipment_type, Booking.check_out_date.is_(None))
        .all()
    }
    return [eid for eid in fleet_ids if eid not in checked_out_ids]


def pick_most_idle_equipment(db: Session, equipment_ids: list) -> str:
    """
    Picks the equipment with the highest average idle_hours_per_day across
    its booking history, among machines currently available - prefers
    machines whose idle time we're most trying to reduce going forward.
    Equipment with NO booking history is treated as maximally idle
    (never used = most idle possible) and is picked first.
    """
    avg_idle_by_equipment = dict(
        db.query(Booking.equipment_id, func.avg(Booking.idle_hours_per_day))
        .filter(Booking.equipment_id.in_(equipment_ids))
        .group_by(Booking.equipment_id)
        .all()
    )

    def idle_score(equipment_id: str) -> float:
        return avg_idle_by_equipment.get(equipment_id, float("inf"))

    return max(equipment_ids, key=idle_score)


def _generate_booking_id(db: Session) -> str:
    last = db.query(Booking).order_by(Booking.id.desc()).first()
    if last is None or not last.booking_id:
        return "BKG1000"
    last_num = int(last.booking_id.replace("BKG", ""))
    return f"BKG{last_num + 1}"


def check_in(
    db: Session,
    equipment_type: str,
    site_id: str,
    check_in_date: date,
    rental_days: int,
    operator_id: str,
    fleet_by_type: dict,
) -> dict:
    """
    1. Find available equipment of the requested type.
    2. If none available -> return a clear failure result.
    3. Otherwise pick the most idle candidate and create a new OPEN booking.
    """
    if rental_days <= 0:
        return {"success": False, "message": "Rental days must be a positive number."}

    fleet_ids = fleet_by_type.get(equipment_type, [])
    if not fleet_ids:
        return {"success": False, "message": f"Unknown equipment type: {equipment_type}"}

    available = get_available_equipment_ids(db, equipment_type, fleet_ids)

    if not available:
        return {"success": False, "message": f"No {equipment_type} available right now."}

    chosen_equipment_id = pick_most_idle_equipment(db, available)

    booking = Booking(
        booking_id=_generate_booking_id(db),
        equipment_id=chosen_equipment_id,
        type=equipment_type,
        site_id=site_id,
        check_in_date=check_in_date,
        check_out_date=None,             # open booking - not yet returned
        engine_hours_per_day=None,        # populated later by usage logging
        idle_hours_per_day=None,
        rental_days=rental_days,          # PLANNED/agreed duration
        last_operator_id=operator_id,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)

    return {
        "success": True,
        "message": f"{chosen_equipment_id} assigned to {operator_id} at site {site_id} for {rental_days} days.",
        "booking_id": booking.booking_id,
        "equipment_id": chosen_equipment_id,
    }


def check_out(
    db: Session,
    operator_id: str,
    equipment_type: str,
    site_id: str,
    check_in_date: date,
) -> dict:
    """
    Finds the OPEN booking matching (operator_id, type, site, check_in_date)
    and closes it by setting Check-Out Date to today.
    """
    booking = (
        db.query(Booking)
        .filter(
            Booking.last_operator_id == operator_id,
            Booking.type == equipment_type,
            Booking.site_id == site_id,
            Booking.check_in_date == check_in_date,
            Booking.check_out_date.is_(None),
        )
        .first()
    )

    if booking is None:
        return {
            "success": False,
            "message": "No open booking found matching that operator, type, site, and check-in date.",
        }

    today = date.today()
    booking.check_out_date = today
    db.commit()
    db.refresh(booking)

    planned_checkout = check_in_date + timedelta(days=booking.rental_days)
    late_days = (today - planned_checkout).days

    return {
        "success": True,
        "message": (
            f"{booking.equipment_id} checked in by {operator_id} returned."
            + (f" Returned {late_days} day(s) late." if late_days > 0 else " Returned on time.")
        ),
        "booking_id": booking.booking_id,
        "equipment_id": booking.equipment_id,
        "check_out_date": str(today),
        "days_late": max(late_days, 0),
    }