"""Auth, metadata, technician search and customer bookings."""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import time_utils as tu
from ..auth import current_user, issue_token, require_role, verify_password
from ..config import get_settings
from ..db import get_db
from ..models import Booking, Locality, ServiceCategory, User
from ..schemas import BookingIn, LoginIn, SearchIn
from ..services import audit, booking, matching
from ..services.trace import Trace
from .common import finish_trace

router = APIRouter(prefix="/api")

DEMO_BANNER = "Learning demo — fictional providers and simulated bookings."


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password.")
    return {"token": issue_token(user), "user": user_public(user)}


def user_public(u: User) -> dict:
    return {"id": u.id, "email": u.email, "display_name": u.display_name, "role": u.role,
            "technician_id": u.technician_id}


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return user_public(user)


@router.get("/meta")
def meta(db: Session = Depends(get_db)):
    s = get_settings()
    from ..services.llm.providers import embedding_info

    return {
        "banner": DEMO_BANNER,
        "today": tu.today_local().isoformat(),
        "today_label": tu.fmt_date(tu.today_local()),
        "timezone": s.display_timezone,
        "categories": [{"code": c.code, "name": c.name, "description": c.description}
                       for c in db.scalars(select(ServiceCategory).order_by(ServiceCategory.code))],
        "localities": [{"code": loc.code, "name": loc.name}
                       for loc in db.scalars(select(Locality).order_by(Locality.name))],
        "time_windows": ["morning", "afternoon", "evening", "any"],
        "ai": {
            "llm_enabled": s.llm_enabled,
            "llm_provider": s.llm_provider if s.llm_enabled else "none",
            "embedding": embedding_info(),
        },
        "charges_note": "Visiting charges cover the technician's visit and diagnosis. "
                        "They are not necessarily the final repair price.",
    }


@router.post("/technicians/search")
def search(body: SearchIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    trace = Trace(kind="technician_search")
    trace.add("input", "Validated search fields", **body.model_dump(mode="json"))
    try:
        with trace.step("technician_matching", "Read-only SQL: active technicians × category × locality × free slots") as d:
            res = matching.search(db, matching.SearchCriteria(body.category, body.locality, body.preferred_date,
                                                              body.time_window))
            d.update(sql=res.sql, params=res.params, technicians_found=len(res.technicians), widened=res.widened)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    trace.outcome = f"{len(res.technicians)} technician(s)"
    return finish_trace(request, trace, user.id, {
        "criteria": {**body.model_dump(mode="json"), "date_label": tu.fmt_date(body.preferred_date)},
        "technicians": res.technicians,
        "widened": res.widened,
        "charges_note": "Visiting charge only — the final repair price is quoted after diagnosis.",
    })


@router.post("/bookings", status_code=201)
def create_booking(
    body: BookingIn,
    request: Request,
    idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    user: User = Depends(require_role("customer")),
    db: Session = Depends(get_db),
):
    trace = Trace(kind="booking")
    trace.add("input", "Validated booking fields", **body.model_dump(), idempotency_key_present=bool(idempotency_key))
    req = booking.BookingRequest(body.slot_id, body.technician_id, body.category, body.locality,
                                 body.issue_description)
    try:
        with trace.step("booking_rules", "Transaction: lock slot row, validate, insert, commit") as d:
            try:
                result, replayed = booking.create_booking(db, user, req, idempotency_key, trace.request_id)
            finally:
                d.update(checks=req.checks)
    except booking.BookingError as err:
        trace.outcome = f"rejected: {err.code}"
        finish_trace(request, trace, user.id, {})
        raise HTTPException(err.http_status, {"code": err.code, "message": err.message,
                                              "request_id": trace.request_id, **err.details}) from err
    trace.outcome = "replayed existing booking" if replayed else f"booking {result['reference']} confirmed"
    return finish_trace(request, trace, user.id, {"booking": result, "replayed": replayed})


@router.get("/bookings/mine")
def my_bookings(user: User = Depends(require_role("customer")), db: Session = Depends(get_db)):
    rows = db.scalars(select(Booking).where(Booking.customer_id == user.id).order_by(Booking.id.desc())).all()
    return {"bookings": [booking.booking_to_dict(db, b) for b in rows]}


@router.get("/bookings/{booking_id}")
def get_booking(booking_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b = db.get(Booking, booking_id)
    visible = b is not None and (
        user.role == "admin"
        or (user.role == "customer" and b.customer_id == user.id)
        or (user.role == "provider" and b.technician_id == user.technician_id)
    )
    if not visible:
        raise HTTPException(404, "Booking not found.")
    return booking.booking_to_dict(db, b)


@router.post("/bookings/{booking_id}/cancel")
def cancel(booking_id: int, request: Request, user: User = Depends(require_role("customer")),
           db: Session = Depends(get_db)):
    trace = Trace(kind="cancel")
    try:
        result = booking.change_status(db, user, booking_id, "cancelled_by_customer", "Cancelled by customer",
                                       trace.request_id)
    except booking.BookingError as err:
        db.rollback()
        audit.record(db, request_id=trace.request_id, action="booking.cancel", outcome=f"rejected:{err.code}",
                     actor_user_id=user.id, entity_type="booking", entity_id=booking_id)
        db.commit()
        raise HTTPException(err.http_status, {"code": err.code, "message": err.message, **err.details}) from err
    return {"booking": result}
