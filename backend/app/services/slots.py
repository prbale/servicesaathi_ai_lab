"""Provider slot management. Slots with an active booking are protected twice:
here (friendly error) and by the `availability_slots_protect` database trigger."""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from .. import time_utils as tu
from ..models import ACTIVE_BOOKING_STATUSES, AvailabilitySlot, Booking, User
from . import audit, matching
from .booking import BookingError


def _active_booking(db: Session, slot_id: int):
    return db.scalar(select(Booking).where(Booking.slot_id == slot_id, Booking.status.in_(ACTIVE_BOOKING_STATUSES)))


def slot_dict(db: Session, s: AvailabilitySlot) -> dict:
    b = _active_booking(db, s.id)
    return {
        "slot_id": s.id,
        "start_at": tu.to_local(s.start_at).isoformat(),
        "label": tu.fmt_local(s.start_at),
        "is_withdrawn": s.is_withdrawn,
        "booking_reference": b.reference if b else None,
        "locked": b is not None,
    }


def list_slots(db: Session, provider: User) -> list[dict]:
    rows = db.scalars(
        select(AvailabilitySlot)
        .where(AvailabilitySlot.technician_id == provider.technician_id, AvailabilitySlot.start_at > tu.now())
        .order_by(AvailabilitySlot.start_at)
    ).all()
    return [slot_dict(db, s) for s in rows]


def _validate_start(d: date, hour: int):
    if not 6 <= hour <= 21:
        raise BookingError("invalid_hour", "Slots can start between 06:00 and 21:00.")
    start = tu.local_dt(d, hour)
    if start <= tu.now():
        raise BookingError("slot_in_past", "Slots must be in the future.")
    if start >= matching.horizon_end():
        raise BookingError("slot_too_far", "Slots can only be published for the next 7 days.")
    return start


def add_slot(db: Session, provider: User, d: date, hour: int, request_id: str) -> dict:
    start = _validate_start(d, hour)
    slot = AvailabilitySlot(technician_id=provider.technician_id, start_at=start, end_at=start + timedelta(hours=1))
    db.add(slot)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise BookingError("slot_overlap", "You already have a slot overlapping that hour.", 409) from exc
    audit.record(db, request_id=request_id, action="slot.add", outcome="success", actor_user_id=provider.id,
                 entity_type="slot", entity_id=slot.id)
    db.commit()
    return slot_dict(db, slot)


def _own_slot(db: Session, provider: User, slot_id: int) -> AvailabilitySlot:
    slot = db.scalar(select(AvailabilitySlot).where(AvailabilitySlot.id == slot_id).with_for_update())
    if slot is None or slot.technician_id != provider.technician_id:
        raise BookingError("not_found", "Slot not found.", 404)
    if slot.start_at <= tu.now():
        raise BookingError("slot_in_past", "Past slots cannot be changed.", 409)
    if _active_booking(db, slot.id):
        raise BookingError("slot_locked", "This slot has an active booking, so it cannot be changed or removed.", 409)
    return slot


def move_slot(db: Session, provider: User, slot_id: int, d: date, hour: int, request_id: str) -> dict:
    slot = _own_slot(db, provider, slot_id)
    start = _validate_start(d, hour)
    slot.start_at, slot.end_at = start, start + timedelta(hours=1)
    try:
        db.flush()
    except (IntegrityError, DBAPIError) as exc:
        db.rollback()
        raise BookingError("slot_overlap", "That hour overlaps another of your slots.", 409) from exc
    audit.record(db, request_id=request_id, action="slot.move", outcome="success", actor_user_id=provider.id,
                 entity_type="slot", entity_id=slot.id)
    db.commit()
    return slot_dict(db, slot)


def remove_slot(db: Session, provider: User, slot_id: int, request_id: str) -> dict:
    """Delete a never-booked slot; withdraw (soft-delete) one that has cancelled booking history."""
    slot = _own_slot(db, provider, slot_id)
    has_history = db.scalar(select(Booking.id).where(Booking.slot_id == slot.id).limit(1)) is not None
    if has_history:
        slot.is_withdrawn = True
        action = "withdrawn"
    else:
        db.delete(slot)
        action = "deleted"
    db.flush()
    audit.record(db, request_id=request_id, action=f"slot.{action}", outcome="success", actor_user_id=provider.id,
                 entity_type="slot", entity_id=slot_id)
    db.commit()
    return {"slot_id": slot_id, "result": action}
