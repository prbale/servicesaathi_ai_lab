"""Provider screens: assigned bookings, status updates, slot management."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_role
from ..db import get_db
from ..models import Booking, Technician, User
from ..schemas import SlotIn, StatusChangeIn
from ..services import booking, slots
from ..services.trace import new_request_id

router = APIRouter(prefix="/api/provider")
provider_only = require_role("provider")


def _err(err: booking.BookingError):
    return HTTPException(err.http_status, {"code": err.code, "message": err.message, **err.details})


@router.get("/me")
def me(user: User = Depends(provider_only), db: Session = Depends(get_db)):
    t = db.get(Technician, user.technician_id)
    return {"technician_id": t.id, "name": t.name, "is_active": t.is_active,
            "categories": [{"code": c.category_code, "visiting_charge_inr": c.visiting_charge_inr} for c in t.categories],
            "localities": [a.locality_code for a in t.areas]}


@router.get("/bookings")
def assigned(user: User = Depends(provider_only), db: Session = Depends(get_db)):
    rows = db.scalars(select(Booking).where(Booking.technician_id == user.technician_id)
                      .order_by(Booking.id.desc())).all()
    out = []
    for b in rows:
        d = booking.booking_to_dict(db, b)
        d.pop("can_cancel", None)
        d["allowed_transitions"] = [s for s, role in booking.TRANSITIONS.get(b.status, {}).items() if role == "provider"]
        out.append(d)
    return {"bookings": out}


@router.post("/bookings/{booking_id}/status")
def update_status(booking_id: int, body: StatusChangeIn, user: User = Depends(provider_only),
                  db: Session = Depends(get_db)):
    try:
        return {"booking": booking.change_status(db, user, booking_id, body.to_status, body.reason, new_request_id())}
    except booking.BookingError as err:
        db.rollback()
        raise _err(err) from err


@router.get("/slots")
def list_slots(user: User = Depends(provider_only), db: Session = Depends(get_db)):
    return {"slots": slots.list_slots(db, user)}


@router.post("/slots", status_code=201)
def add_slot(body: SlotIn, user: User = Depends(provider_only), db: Session = Depends(get_db)):
    try:
        return slots.add_slot(db, user, body.date, body.hour, new_request_id())
    except booking.BookingError as err:
        db.rollback()
        raise _err(err) from err


@router.patch("/slots/{slot_id}")
def move_slot(slot_id: int, body: SlotIn, user: User = Depends(provider_only), db: Session = Depends(get_db)):
    try:
        return slots.move_slot(db, user, slot_id, body.date, body.hour, new_request_id())
    except booking.BookingError as err:
        db.rollback()
        raise _err(err) from err


@router.delete("/slots/{slot_id}")
def remove_slot(slot_id: int, user: User = Depends(provider_only), db: Session = Depends(get_db)):
    try:
        return slots.remove_slot(db, user, slot_id, new_request_id())
    except booking.BookingError as err:
        db.rollback()
        raise _err(err) from err
