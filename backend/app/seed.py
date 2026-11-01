"""Reproducible demo data. All providers, customers and bookings are FICTIONAL.

    python -m app.seed            # reset + seed everything (directory, users, slots, policies, model registry)

Slots are generated relative to *today* (Asia/Kolkata) with a fixed random seed, so the
demo always has availability for the next seven days and runs are reproducible per day.
"""
import random
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from . import time_utils as tu
from .auth import hash_password
from .db import session_scope
from .models import (
    AvailabilitySlot,
    Locality,
    ServiceCategory,
    Technician,
    TechnicianCategory,
    TechnicianServiceArea,
    User,
)

DEMO_PASSWORD = "demo1234"  # shown on the login screen; demo only

CATEGORIES = [
    ("plumbing", "Plumbing", "Leaks, taps, pipes, drains, toilets, water tanks and pumps."),
    ("electrical", "Electrical repairs", "Switches, sockets, wiring faults, MCBs, fans and light fittings."),
    ("appliance", "Appliance servicing", "Washing machines, refrigerators, microwaves, geysers, mixers, RO purifiers."),
]

LOCALITIES = [
    ("wakad", "Wakad", []),
    ("hinjawadi", "Hinjawadi", ["hinjewadi", "hinjawadi phase 1", "hinjawadi phase 2"]),
    ("baner", "Baner", []),
    ("aundh", "Aundh", []),
]

# name, years, rating, {category: visiting charge INR}, [localities], bio
TECHNICIANS = [
    ("Ramesh Kulkarni", 12, 4.7, {"plumbing": 299}, ["wakad", "hinjawadi"], "Leak detection and bathroom fittings."),
    ("Sunita Pawar", 8, 4.5, {"plumbing": 349, "appliance": 399}, ["baner", "aundh"], "Kitchen plumbing and RO units."),
    ("Imran Shaikh", 10, 4.6, {"electrical": 349}, ["wakad", "baner"], "Wiring faults, MCB trips, fan installs."),
    ("Deepak Jadhav", 6, 4.3, {"electrical": 299, "appliance": 349}, ["hinjawadi", "wakad"], "Geysers and switchboards."),
    ("Priya Deshmukh", 9, 4.8, {"appliance": 449}, ["aundh", "baner", "wakad"], "Washing machines and refrigerators."),
    ("Vikas More", 15, 4.4, {"plumbing": 399, "electrical": 399}, ["aundh", "hinjawadi"], "General home repairs."),
    ("Kavita Joshi", 5, 4.2, {"appliance": 299}, ["hinjawadi", "wakad"], "Microwaves, mixers and small appliances."),
    ("Anil Gaikwad", 11, 4.6, {"plumbing": 249}, ["baner", "aundh", "wakad"], "Drain blockages and water tanks."),
    ("Farhan Qureshi", 7, 4.5, {"electrical": 449}, ["aundh", "hinjawadi"], "Inverter wiring and lighting."),
    ("Meera Patil", 4, 4.1, {"appliance": 349, "electrical": 299}, ["baner"], "Appliance diagnostics."),
    ("Santosh Shinde", 13, 4.7, {"plumbing": 349}, ["hinjawadi"], "Pumps and pipeline work."),
    ("Neha Kale", 6, 4.4, {"electrical": 349, "plumbing": 299}, ["wakad", "baner"], "Fixture installation."),
]

CUSTOMERS = [
    ("asha@demo.servicesaathi.local", "Asha (demo customer)"),
    ("rohan@demo.servicesaathi.local", "Rohan (demo customer)"),
    # used only by the Booking Rules Lab to simulate two people racing for one slot
    ("lab.racer.a@demo.servicesaathi.local", "Lab racer A"),
    ("lab.racer.b@demo.servicesaathi.local", "Lab racer B"),
]
ADMIN = ("admin@demo.servicesaathi.local", "Demo admin")

BUSINESS_TABLES = (
    "audit_events, booking_status_events, bookings, availability_slots, users, "
    "technician_service_areas, technician_categories, technicians, localities, service_categories"
)


def provider_email(i: int) -> str:
    return f"provider{i:02d}@demo.servicesaathi.local"


def seed_directory(db: Session) -> None:
    for code, name, desc in CATEGORIES:
        db.add(ServiceCategory(code=code, name=name, description=desc))
    for code, name, aliases in LOCALITIES:
        db.add(Locality(code=code, name=name, aliases=aliases))
    db.flush()
    for name, years, rating, charges, areas, bio in TECHNICIANS:
        t = Technician(name=name, years_experience=years, rating=rating, bio=bio, is_active=True)
        t.categories = [TechnicianCategory(category_code=c, visiting_charge_inr=v) for c, v in charges.items()]
        t.areas = [TechnicianServiceArea(locality_code=loc) for loc in areas]
        db.add(t)
    db.flush()


def seed_users(db: Session) -> None:
    pw = hash_password(DEMO_PASSWORD)  # one hash reused: fine for a demo, faster seeding
    for email, name in CUSTOMERS:
        db.add(User(email=email, display_name=name, role="customer", password_hash=pw))
    techs = db.query(Technician).order_by(Technician.id).all()
    for i, t in enumerate(techs, start=1):
        db.add(User(email=provider_email(i), display_name=f"{t.name} (provider)", role="provider",
                    password_hash=pw, technician_id=t.id))
    db.add(User(email=ADMIN[0], display_name=ADMIN[1], role="admin", password_hash=pw))
    db.flush()


def seed_slots(db: Session, seed: int = 42) -> int:
    """One-hour slots, 09:00–18:00 starts, today (future hours only) + next 7 days."""
    rng = random.Random(seed)
    today = tu.today_local()
    count = 0
    for t in db.query(Technician).order_by(Technician.id).all():
        for day in range(0, 8):
            d = today + timedelta(days=day)
            for hour in range(9, 19):
                if rng.random() > 0.6:
                    continue
                start = tu.local_dt(d, hour)
                if start <= tu.now() + timedelta(minutes=30):
                    continue
                db.add(AvailabilitySlot(technician_id=t.id, start_at=start, end_at=start + timedelta(hours=1)))
                count += 1
    db.flush()
    return count


def reset_business_data(db: Session) -> None:
    db.execute(text(f"TRUNCATE {BUSINESS_TABLES} RESTART IDENTITY CASCADE"))


def seed_all(with_policies: bool = True, with_model: bool = True) -> dict:
    with session_scope() as db:
        reset_business_data(db)
        seed_directory(db)
        seed_users(db)
        slots = seed_slots(db)
    summary = {"technicians": len(TECHNICIANS), "slots": slots, "users": len(CUSTOMERS) + len(TECHNICIANS) + 1}
    if with_policies:
        from .services.rag.ingest import seed_policy_documents

        summary["policies"] = seed_policy_documents()
    if with_model:
        from .services.ml.registry import register_saved_model

        summary["model"] = register_saved_model()
    return summary


if __name__ == "__main__":
    print(seed_all())
