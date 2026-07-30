"""
Check-in (booking creation / equipment goes out) and Check-out
(booking closure / equipment returned) logic.

Terminology matches our existing DB columns: Check-In Date is the earlier
date (equipment goes out), Check-Out Date is the later/return date.
"""

from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import func

from .db_models import Booking

EQUIPMENT_TYPES = ["Excavator", "Crane", "Bulldozer", "Grader"]
FLEET_SIZE_PER_TYPE = 4


def build_fleet_by_type() -> dict:
    """
    Fixed fleet reference (mirrors data_generation.py's build_fleet()):
    4 units per type, IDs assigned sequentially from EQX1001.
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
    check_out_date IS NULL (checked out, not yet returned).
    Everything else of that type is available.
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
    its booking history - prefers machines that have historically sat idle
    the most, directly supporting the "minimize idle time" goal.
    Equipment with NO booking history is treated as maximally idle
    (never used = most idle possible) and gets picked first.
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
    operator_id: str,
    fleet_by_type: dict,
) -> dict:
    """
    1. Find available equipment of the requested type.
    2. If none available -> return a clear failure result.
    3. Otherwise pick the most idle candidate and create a new OPEN booking
       (check_out_date left NULL until check-out happens).
    """
    fleet_ids = fleet_by_type.get(equipment_type, [])
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
        check_out_date=None,
        engine_hours_per_day=None,
        idle_hours_per_day=None,
        rental_days=None,
        last_operator_id=operator_id,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)

    return {
        "success": True,
        "message": f"{chosen_equipment_id} assigned to {operator_id} at site {site_id}.",
        "booking_id": booking.booking_id,
        "equipment_id": chosen_equipment_id,
    }


def check_out(
    db: Session,
    equipment_type: str,
    site_id: str,
    check_in_date: date,
    check_out_date: date,
    operator_id: str = None,
) -> dict:
    """
    Finds the OPEN booking matching (type, site, check_in_date) and closes it.

    CAVEAT: matching by (type, site, check_in_date) rather than a booking_id
    or equipment_id means if two units of the same type were checked in at
    the same site on the same date, this matches whichever row comes first.
    Safer long-term: have the frontend pass back the booking_id it received
    at check-in time instead of re-deriving the row this way.
    """
    booking = (
        db.query(Booking)
        .filter(
            Booking.type == equipment_type,
            Booking.site_id == site_id,
            Booking.check_in_date == check_in_date,
            Booking.check_out_date.is_(None),
        )
        .first()
    )

    if booking is None:
        return {"success": False, "message": "No open booking found matching that type, site, and check-in date."}

    booking.check_out_date = check_out_date
    booking.rental_days = (check_out_date - check_in_date).days
    if operator_id:
        booking.last_operator_id = operator_id

    db.commit()
    db.refresh(booking)

    return {
        "success": True,
        "message": f"{booking.equipment_id} checked out. Rental days: {booking.rental_days}.",
        "booking_id": booking.booking_id,
        "equipment_id": booking.equipment_id,
        "rental_days": booking.rental_days,
    }