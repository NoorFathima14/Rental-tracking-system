"""
SQLAlchemy ORM model — the actual DB table. Kept separate from
`models.py` (pydantic schemas used for API request/response shapes)
so "DB shape" and "API shape" can evolve independently.
"""
from sqlalchemy import Column, Integer, String, Float, Date
from .database import Base


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    booking_id = Column(String, unique=True, index=True)
    equipment_id = Column(String, index=True)
    type = Column(String, index=True)
    site_id = Column(String, nullable=True, index=True)
    check_in_date = Column(Date, nullable=True)
    check_out_date = Column(Date, nullable=True)
    engine_hours_per_day = Column(Float)
    idle_hours_per_day = Column(Float)
    rental_days = Column(Integer, nullable=True)
    last_operator_id = Column(String, nullable=True, index=True)