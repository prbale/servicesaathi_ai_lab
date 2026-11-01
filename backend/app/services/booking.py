"""Booking rules — the deterministic heart of the app.

Double booking is prevented in TWO layers:
  1. `SELECT ... FOR UPDATE` on the slot row serialises concurrent confirmations
     inside a transaction, so the second one sees the first one's booking.
  2. The partial unique index `bookings_one_active_per_slot` makes it impossible
     at the database level, even if application code had a bug.
A frontend availability check is only a hint; it is never trusted.
"""
import hashlib
import json
import secrets
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import time_utils as tu
from ..models import (
    ACTIVE_BOOKING_STATUSES,
    AvailabilitySlot,
    Booking,
    BookingStatusEvent,
    Technician,
    TechnicianCategory,
    TechnicianServiceArea,
    User,
)
from . import audit, matching

CANCELLATION_CUTOFF_HOURS = 2  # mirrors the seeded demo policy document

# from_status -> {to_status: role allowed to make the change}
TRANSITIONS: dict[str, dict[str, str]] = {
    "confirmed": {"en_route": "provider", "cancelled_by_customer": "customer", "cancelled_by_provider": "provider"},
    "en_route": {"in_progress": "provider", "cancelled_by_provider": "provider"},
    "in_progress": {"completed": "provider"},
}

_REF_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L


class BookingError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 422, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details or {}


@dataclass
class BookingRequest:
    slot_id: int
    technician_id: int
    category: str
    locality: str
    issue_description: str
    checks: list[dict] = field(default_factory=list)  # validation outcomes for the trace

    def fingerprint(self) -> str:
        data = [self.slot_id, self.technician_id, self.category, self.locality, self.issue_description.strip()]
        return hashlib.sha256(json.dumps(data).encode()).hexdigest()


def _new_reference() -> str:
    return "SS-" + "".join(secrets.choice(_REF_ALPHABET) for _ in range(6))


def _check(req: BookingRequest, rule: str, ok: bool, detail: str = "") -> bool:
    req.checks.append({"rule": rule, "passed": ok, **({"detail": detail} if detail else {})})
    return ok


def booking_to_dict(db: Session, b: Booking) -> dict:
    slot = db.get(AvailabilitySlot, b.slot_id)
    tech = db.get(Technician, b.technician_id)
    events = db.scalars(
        select(BookingStatusEvent).where(BookingStatusEvent.booking_id == b.id).order_by(BookingStatusEvent.id)
    ).all()
    return {
        "id": b.id,
        "reference": b.reference,
        "status": b.status,
        "category": b.category_code,
        "locality": b.locality_code,
        "issue_description": b.issue_description,
        "visiting_charge_inr": b.visiting_charge_inr,
        "technician": {"id": tech.id, "name": tech.name} if tech else None,
        "slot": {
            "slot_id": slot.id,
            "start_at": tu.to_local(slot.start_at).isoformat(),
            "label": tu.fmt_local(slot.start_at),
        },
        "created_at": tu.to_local(b.created_at).isoformat() if b.created_at else None,
        "history": [
            {
                "from": e.from_status,
                "to": e.to_status,
                "reason": e.reason,
                "at": tu.to_local(e.created_at).isoformat() if e.created_at else None,
            }
            for e in events
        ],
        "can_cancel": b.status == "confirmed"
        and slot.start_at - tu.now() >= timedelta(hours=CANCELLATION_CUTOFF_HOURS),
    }


def alternatives_for(db: Session, req: BookingRequest, slot: AvailabilitySlot | None) -> list[dict]:
    """Fresh alternatives after a conflict — queried again from the database."""
    d = tu.to_local(slot.start_at).date() if slot else tu.today_local()
    try:
        res = matching.search(db, matching.SearchCriteria(req.category, req.locality, d, "any"))
    except ValueError:
        return []
    return res.technicians[:3]


def create_booking(
    db: Session, customer: User, req: BookingRequest, idempotency_key: str, request_id: str
) -> tuple[dict, bool]:
    """Create a booking. Returns (booking_dict, replayed). Raises BookingError."""
    if customer.role != "customer":
        raise BookingError("forbidden", "Only customer accounts can create bookings.", 403)
    if not idempotency_key or len(idempotency_key) > 100:
        raise BookingError("idempotency_key_required", "An Idempotency-Key header (max 100 chars) is required.", 400)
    issue = req.issue_description.strip()
    if not 3 <= len(issue) <= 1000:
        raise BookingError("invalid_issue", "Please describe the problem in 3–1000 characters.")
    fingerprint = req.fingerprint()

    # 1) Idempotency: a retry of the same submission returns the original booking.
    existing = db.scalar(
        select(Booking).where(Booking.customer_id == customer.id, Booking.idempotency_key == idempotency_key)
    )
    if existing is not None:
        _check(req, "idempotency", True, "Same key seen before; returning the original booking.")
        if existing.request_fingerprint != fingerprint:
            raise BookingError(
                "idempotency_key_reused",
                "This Idempotency-Key was already used for a different booking request.",
                409,
            )
        return booking_to_dict(db, existing), True
    _check(req, "idempotency", True, "New submission key.")

    try:
        # 2) Lock the slot row. A concurrent confirmation of the same slot waits here.
        slot = db.scalar(select(AvailabilitySlot).where(AvailabilitySlot.id == req.slot_id).with_for_update())
        if not _check(req, "slot_exists", slot is not None):
            raise BookingError("slot_not_found", "That time slot no longer exists.", 404)
        if not _check(req, "slot_belongs_to_technician", slot.technician_id == req.technician_id):
            raise BookingError("slot_mismatch", "That slot does not belong to the selected technician.")
        if not _check(req, "slot_not_withdrawn", not slot.is_withdrawn):
            raise BookingError("slot_withdrawn", "The technician has withdrawn that slot.", 409,
                               {"alternatives": alternatives_for(db, req, slot)})
        if not _check(req, "slot_in_future", slot.start_at > tu.now(), tu.fmt_local(slot.start_at)):
            raise BookingError("slot_in_past", "That slot has already started or passed. Please pick a future slot.")
        if not _check(req, "slot_within_horizon", slot.start_at < matching.horizon_end()):
            raise BookingError("slot_too_far", "Bookings open only for the next 7 days.")

        tech = db.get(Technician, req.technician_id)
        if not _check(req, "technician_active", bool(tech and tech.is_active)):
            raise BookingError("technician_unavailable", "That technician is not currently accepting bookings.")
        offer = db.get(TechnicianCategory, (req.technician_id, req.category))
        if not _check(req, "technician_offers_category", offer is not None, req.category):
            raise BookingError("category_mismatch", f"{tech.name} does not offer {req.category} services.")
        area = db.get(TechnicianServiceArea, (req.technician_id, req.locality))
        if not _check(req, "technician_serves_locality", area is not None, req.locality):
            raise BookingError("locality_mismatch", f"{tech.name} does not serve that locality.")

        # 3) Is the slot already taken? (we hold the slot lock, so this read is reliable)
        taken = db.scalar(
            select(Booking.id).where(Booking.slot_id == slot.id, Booking.status.in_(ACTIVE_BOOKING_STATUSES))
        )
        if not _check(req, "slot_free", taken is None):
            raise BookingError(
                "slot_taken",
                "Sorry — someone else just booked that slot. Here are other free slots.",
                409,
                {"alternatives": alternatives_for(db, req, slot)},
            )

        booking = Booking(
            reference=_new_reference(),
            customer_id=customer.id,
            technician_id=req.technician_id,
            slot_id=slot.id,
            category_code=req.category,
            locality_code=req.locality,
            issue_description=issue,
            visiting_charge_inr=offer.visiting_charge_inr,  # snapshot from DB, not from the client
            status="confirmed",
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
        )
        db.add(booking)
        db.flush()  # the unique indexes are checked here
        db.add(BookingStatusEvent(booking_id=booking.id, from_status=None, to_status="confirmed",
                                  actor_user_id=customer.id, reason="Booked by customer"))
        audit.record(db, request_id=request_id, action="booking.create", outcome="success",
                     actor_user_id=customer.id, entity_type="booking", entity_id=booking.id,
                     details={"reference": booking.reference, "slot_id": slot.id, "technician_id": tech.id})
        db.commit()
        _check(req, "database_constraints", True, "Insert committed.")
        return booking_to_dict(db, booking), False

    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", "") or ""
        if constraint == "bookings_one_active_per_slot":
            _check(req, "database_constraints", False, "Unique index rejected a second active booking.")
            slot = db.get(AvailabilitySlot, req.slot_id)
            raise BookingError("slot_taken", "Sorry — someone else just booked that slot. Here are other free slots.",
                               409, {"alternatives": alternatives_for(db, req, slot)}) from exc
        if constraint == "bookings_customer_id_idempotency_key_key":
            existing = db.scalar(select(Booking).where(Booking.customer_id == customer.id,
                                                       Booking.idempotency_key == idempotency_key))
            return booking_to_dict(db, existing), True
        raise BookingError("constraint_violation", f"Database rejected the booking ({constraint}).") from exc
    except BookingError as err:
        db.rollback()
        audit.record(db, request_id=request_id, action="booking.create", outcome=f"rejected:{err.code}",
                     actor_user_id=customer.id, entity_type="slot", entity_id=req.slot_id)
        db.commit()
        raise


def change_status(db: Session, actor: User, booking_id: int, to_status: str, reason: str, request_id: str) -> dict:
    """Apply a permitted status transition with ownership checks."""
    booking = db.scalar(select(Booking).where(Booking.id == booking_id).with_for_update())
    if booking is None:
        raise BookingError("not_found", "Booking not found.", 404)

    # Ownership: customers only their own bookings, providers only bookings assigned to them.
    if actor.role == "customer" and booking.customer_id != actor.id:
        raise BookingError("not_found", "Booking not found.", 404)  # do not reveal it exists
    if actor.role == "provider" and booking.technician_id != actor.technician_id:
        raise BookingError("not_found", "Booking not found.", 404)
    if actor.role == "admin":
        raise BookingError("forbidden", "Admins can inspect bookings but not change their status in this demo.", 403)

    allowed = TRANSITIONS.get(booking.status, {})
    if to_status not in allowed:
        raise BookingError("invalid_transition", f"Cannot change a '{booking.status}' booking to '{to_status}'.",
                           409, {"allowed": [s for s, r in allowed.items() if r == actor.role]})
    if allowed[to_status] != actor.role:
        raise BookingError("forbidden", f"A {actor.role} cannot make this change.", 403)

    if to_status == "cancelled_by_customer":
        slot = db.get(AvailabilitySlot, booking.slot_id)
        if slot.start_at - tu.now() < timedelta(hours=CANCELLATION_CUTOFF_HOURS):
            raise BookingError(
                "cancellation_window_closed",
                f"Online cancellation closes {CANCELLATION_CUTOFF_HOURS} hours before the visit (demo policy).",
                409,
            )

    previous = booking.status
    booking.status = to_status
    booking.updated_at = tu.now()
    db.add(BookingStatusEvent(booking_id=booking.id, from_status=previous, to_status=to_status,
                              actor_user_id=actor.id, reason=reason[:300]))
    audit.record(db, request_id=request_id, action="booking.status_change", outcome="success",
                 actor_user_id=actor.id, entity_type="booking", entity_id=booking.id,
                 details={"from": previous, "to": to_status})
    db.commit()
    return booking_to_dict(db, booking)
