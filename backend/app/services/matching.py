"""Technician matching: SQL over the directory and availability tables.

Everything here is read-only and parameterised. Availability and charges always come
from the database — never from a model or a document.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import and_, exists, func, not_, select
from sqlalchemy.orm import Session

from .. import time_utils as tu
from ..models import (
    ACTIVE_BOOKING_STATUSES,
    AvailabilitySlot,
    Booking,
    Locality,
    ServiceCategory,
    Technician,
    TechnicianCategory,
    TechnicianServiceArea,
)

BOOKING_HORIZON_DAYS = 7


@dataclass
class SearchCriteria:
    category: str
    locality: str
    preferred_date: date
    time_window: str = "any"


@dataclass
class SearchResult:
    criteria: SearchCriteria
    technicians: list[dict]
    widened: str | None = None  # explains if we had to widen the time window
    sql: str = ""
    params: dict = field(default_factory=dict)


def horizon_end() -> datetime:
    return tu.local_dt(tu.today_local(), 0) + timedelta(days=BOOKING_HORIZON_DAYS + 1)


def free_slot_condition():
    """SQL condition: the slot has no active (non-cancelled) booking."""
    return not_(
        exists().where(
            and_(Booking.slot_id == AvailabilitySlot.id, Booking.status.in_(ACTIVE_BOOKING_STATUSES))
        )
    )


def build_query(category: str, locality: str, start: datetime, end: datetime):
    """One SELECT joining technicians → categories → service areas → free future slots."""
    return (
        select(
            Technician.id,
            Technician.name,
            Technician.rating,
            Technician.years_experience,
            TechnicianCategory.visiting_charge_inr,
            AvailabilitySlot.id.label("slot_id"),
            AvailabilitySlot.start_at,
            AvailabilitySlot.end_at,
        )
        .join(TechnicianCategory, TechnicianCategory.technician_id == Technician.id)
        .join(TechnicianServiceArea, TechnicianServiceArea.technician_id == Technician.id)
        .join(AvailabilitySlot, AvailabilitySlot.technician_id == Technician.id)
        .where(
            Technician.is_active.is_(True),
            TechnicianCategory.category_code == category,
            TechnicianServiceArea.locality_code == locality,
            AvailabilitySlot.is_withdrawn.is_(False),
            AvailabilitySlot.start_at >= start,
            AvailabilitySlot.start_at < end,
            AvailabilitySlot.start_at > tu.now(),
            free_slot_condition(),
        )
        .order_by(AvailabilitySlot.start_at, Technician.rating.desc(), Technician.id)
    )


def _group(rows, category_name: str, locality_name: str, window_label: str) -> list[dict]:
    techs: dict[int, dict] = {}
    for r in rows:
        t = techs.setdefault(
            r.id,
            {
                "technician_id": r.id,
                "name": r.name,
                "rating": float(r.rating),
                "years_experience": r.years_experience,
                "visiting_charge_inr": r.visiting_charge_inr,
                "slots": [],
            },
        )
        t["slots"].append(
            {
                "slot_id": r.slot_id,
                "start_at": tu.to_local(r.start_at).isoformat(),
                "end_at": tu.to_local(r.end_at).isoformat(),
                "label": tu.to_local(r.start_at).strftime("%a %d %b, %H:%M"),
            }
        )
    out = []
    for t in techs.values():
        t["match_reasons"] = [
            f"Offers {category_name}",
            f"Serves {locality_name}",
            f"{len(t['slots'])} free one-hour slot(s) {window_label}",
            f"Rated {t['rating']:.1f} · {t['years_experience']} yrs experience",
        ]
        out.append(t)
    return out


def search(db: Session, criteria: SearchCriteria) -> SearchResult:
    cat = db.get(ServiceCategory, criteria.category)
    loc = db.get(Locality, criteria.locality)
    if cat is None:
        raise ValueError(f"Unknown category '{criteria.category}'.")
    if loc is None:
        raise ValueError(f"Unknown locality '{criteria.locality}'.")

    start, end = tu.window_bounds(criteria.preferred_date, criteria.time_window)
    end = min(end, horizon_end())
    window_label = f"on {tu.fmt_date(criteria.preferred_date)}, {tu.describe_window(criteria.time_window)}"
    stmt = build_query(criteria.category, criteria.locality, start, end)
    rows = db.execute(stmt).all()
    widened = None

    if not rows and criteria.time_window != "any":
        # Same day, any time
        start, end = tu.window_bounds(criteria.preferred_date, "any")
        stmt = build_query(criteria.category, criteria.locality, start, end)
        rows = db.execute(stmt).all()
        window_label = f"on {tu.fmt_date(criteria.preferred_date)} (any time)"
        widened = "No free slots in your preferred window, so showing other times that day."
    if not rows:
        # Next days inside the booking horizon
        start = tu.local_dt(criteria.preferred_date, 0) + timedelta(days=1)
        stmt = build_query(criteria.category, criteria.locality, start, horizon_end())
        rows = db.execute(stmt).all()
        window_label = "in the next few days"
        widened = "No free slots on your preferred date, so showing the next available days."

    compiled = stmt.compile()
    return SearchResult(
        criteria=criteria,
        technicians=_group(rows, cat.name, loc.name, window_label),
        widened=widened,
        sql=str(compiled),
        params={k: str(v) for k, v in compiled.params.items()},
    )


def charge_summary(db: Session, category: str | None = None) -> list[dict]:
    """Live visiting-charge ranges per category (used to answer 'how much' questions)."""
    stmt = (
        select(
            TechnicianCategory.category_code,
            func.min(TechnicianCategory.visiting_charge_inr),
            func.max(TechnicianCategory.visiting_charge_inr),
            func.count(),
        )
        .join(Technician, Technician.id == TechnicianCategory.technician_id)
        .where(Technician.is_active.is_(True))
        .group_by(TechnicianCategory.category_code)
        .order_by(TechnicianCategory.category_code)
    )
    if category:
        stmt = stmt.where(TechnicianCategory.category_code == category)
    return [
        {"category": c, "min_inr": lo, "max_inr": hi, "technicians": n} for c, lo, hi, n in db.execute(stmt).all()
    ]


def free_slot_counts(db: Session, category: str | None, locality: str | None, d: date | None) -> dict:
    """Live count of free slots (used to answer availability questions)."""
    start = tu.local_dt(d, 0) if d else tu.now()
    end = start + timedelta(days=1) if d else horizon_end()
    stmt = (
        select(func.count(func.distinct(AvailabilitySlot.id)))
        .select_from(AvailabilitySlot)
        .join(Technician, Technician.id == AvailabilitySlot.technician_id)
        .where(
            Technician.is_active.is_(True),
            AvailabilitySlot.is_withdrawn.is_(False),
            AvailabilitySlot.start_at > tu.now(),
            AvailabilitySlot.start_at >= start,
            AvailabilitySlot.start_at < end,
            free_slot_condition(),
        )
    )
    if category:
        stmt = stmt.join(TechnicianCategory, TechnicianCategory.technician_id == Technician.id).where(
            TechnicianCategory.category_code == category
        )
    if locality:
        stmt = stmt.join(TechnicianServiceArea, TechnicianServiceArea.technician_id == Technician.id).where(
            TechnicianServiceArea.locality_code == locality
        )
    return {"free_slots": db.execute(stmt).scalar_one(), "category": category, "locality": locality,
            "date": d.isoformat() if d else None}
