"""Booking correctness: matching, double-booking under concurrency, idempotency,
cancellation and slot release, status transitions, and role/ownership enforcement."""
import threading
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app import time_utils as tu
from app.db import new_session
from app.models import AvailabilitySlot, Booking, User
from app.services import booking as svc
from tests.conftest import ADMIN, ASHA, ROHAN, login, provider

TOMORROW = None


def search(client, headers, category="plumbing", locality="wakad", window="any", days=1):
    d = (tu.today_local() + timedelta(days=days)).isoformat()
    r = client.post("/api/technicians/search", headers=headers,
                    json={"category": category, "locality": locality, "preferred_date": d, "time_window": window})
    assert r.status_code == 200, r.text
    return r.json()


def first_offer(client, headers, **kw):
    res = search(client, headers, **kw)
    t = res["technicians"][0]
    return t, t["slots"][0]


def book(client, headers, tech, slot, key=None, category="plumbing", locality="wakad", issue="Kitchen tap leaking"):
    return client.post(
        "/api/bookings",
        headers={**headers, "Idempotency-Key": key or str(uuid.uuid4())},
        json={"slot_id": slot["slot_id"], "technician_id": tech["technician_id"], "category": category,
              "locality": locality, "issue_description": issue},
    )


# ------------------------------------------------------------------ matching
def test_search_matches_category_locality_and_free_slots(seeded, client):
    h = login(client, ASHA)
    res = search(client, h, category="electrical", locality="aundh")
    assert res["technicians"], "seed guarantees at least two electricians in Aundh"
    with new_session() as db:
        for t in res["technicians"]:
            cats = {r[0] for r in db.execute(text(
                "select category_code from technician_categories where technician_id=:t"), {"t": t["technician_id"]})}
            areas = {r[0] for r in db.execute(text(
                "select locality_code from technician_service_areas where technician_id=:t"),
                {"t": t["technician_id"]})}
            assert "electrical" in cats and "aundh" in areas
            assert any("Serves Aundh" in reason for reason in t["match_reasons"])
            for s in t["slots"]:
                assert s["start_at"] > tu.now().isoformat()[:10]


def test_morning_window_filters_by_local_time(seeded, client):
    h = login(client, ASHA)
    res = search(client, h, window="morning")
    if res["widened"]:
        pytest.skip("no morning slots in today's seed; widening is tested elsewhere")
    for t in res["technicians"]:
        for s in t["slots"]:
            hour = int(s["start_at"][11:13])
            assert 8 <= hour < 12, s


def test_charges_come_from_database(seeded, client):
    h = login(client, ASHA)
    tech, slot = first_offer(client, h)
    with new_session() as db:
        db_charge = db.execute(text("select visiting_charge_inr from technician_categories "
                                    "where technician_id=:t and category_code='plumbing'"),
                               {"t": tech["technician_id"]}).scalar()
    assert tech["visiting_charge_inr"] == db_charge
    r = book(client, h, tech, slot)
    assert r.status_code == 201
    assert r.json()["booking"]["visiting_charge_inr"] == db_charge


# ------------------------------------------------------------ double booking
def test_concurrent_confirmations_exactly_one_wins(seeded, client):
    """Two customers confirm the same slot at the same moment, through the real service layer."""
    h = login(client, ASHA)
    tech, slot = first_offer(client, h)
    with new_session() as db:
        racers = [db.scalar(select(User).where(User.email == e)) for e in (ASHA, ROHAN)]
    barrier = threading.Barrier(2)
    results: list = [None, None]

    def attempt(i: int):
        db = new_session()
        try:
            req = svc.BookingRequest(slot["slot_id"], tech["technician_id"], "plumbing", "wakad", "Leaking tap")
            barrier.wait()
            results[i] = ("ok", svc.create_booking(db, racers[i], req, f"race-{i}", "req_test")[0]["reference"])
        except svc.BookingError as err:
            results[i] = ("error", err.code, err.http_status, err.details)
        finally:
            db.close()

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    outcomes = sorted(r[0] for r in results)
    assert outcomes == ["error", "ok"], results
    loser = next(r for r in results if r[0] == "error")
    assert loser[1] == "slot_taken" and loser[2] == 409
    assert "alternatives" in loser[3]
    assert all(a["slots"][0]["slot_id"] != slot["slot_id"] for a in loser[3]["alternatives"])
    with new_session() as db:
        n = db.scalar(text("select count(*) from bookings where slot_id=:s and status='confirmed'"),
                      {"s": slot["slot_id"]})
    assert n == 1


def test_database_index_blocks_double_booking_even_without_app_checks(seeded, client):
    """Bypass the service: insert two active bookings directly. The unique index must refuse."""
    h = login(client, ASHA)
    tech, slot = first_offer(client, h)
    assert book(client, h, tech, slot).status_code == 201
    with new_session() as db:
        b = db.scalar(select(Booking))
        dup = Booking(reference="SS-DUPLI", customer_id=b.customer_id + 1, technician_id=b.technician_id,
                      slot_id=b.slot_id, category_code=b.category_code, locality_code=b.locality_code,
                      issue_description="dup", visiting_charge_inr=1, status="confirmed",
                      idempotency_key="direct", request_fingerprint="x")
        db.add(dup)
        with pytest.raises(IntegrityError) as exc:
            db.flush()
        assert "bookings_one_active_per_slot" in str(exc.value)


def test_second_booking_of_taken_slot_gets_conflict_and_alternatives(seeded, client):
    a, r_ = login(client, ASHA), login(client, ROHAN)
    tech, slot = first_offer(client, a)
    assert book(client, a, tech, slot).status_code == 201
    r = book(client, r_, tech, slot)
    assert r.status_code == 409
    body = r.json()["detail"]
    assert body["code"] == "slot_taken" and isinstance(body["alternatives"], list)


# --------------------------------------------------------------- idempotency
def test_idempotent_retry_returns_same_booking(seeded, client):
    h = login(client, ASHA)
    tech, slot = first_offer(client, h)
    r1 = book(client, h, tech, slot, key="retry-123")
    r2 = book(client, h, tech, slot, key="retry-123")
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["booking"]["reference"] == r2.json()["booking"]["reference"]
    assert r2.json()["replayed"] is True
    with new_session() as db:
        assert db.scalar(text("select count(*) from bookings")) == 1


def test_idempotency_key_reused_with_different_payload_is_rejected(seeded, client):
    h = login(client, ASHA)
    tech, slot = first_offer(client, h)
    assert book(client, h, tech, slot, key="k1").status_code == 201
    r = book(client, h, tech, slot, key="k1", issue="A different problem entirely")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "idempotency_key_reused"


def test_missing_idempotency_key_is_rejected(seeded, client):
    h = login(client, ASHA)
    tech, slot = first_offer(client, h)
    r = client.post("/api/bookings", headers=h, json={
        "slot_id": slot["slot_id"], "technician_id": tech["technician_id"], "category": "plumbing",
        "locality": "wakad", "issue_description": "Leak"})
    assert r.status_code == 400


# ---------------------------------------------------------- validation rules
def test_invalid_category_locality_combination_rejected(seeded, client):
    h = login(client, ASHA)
    tech, slot = first_offer(client, h, category="plumbing", locality="wakad")
    r = book(client, h, tech, slot, category="appliance")  # Ramesh/Anil/Neha don't all do appliances
    with new_session() as db:
        offers = db.scalar(text("select count(*) from technician_categories where technician_id=:t and "
                                "category_code='appliance'"), {"t": tech["technician_id"]})
    if offers:
        pytest.skip("first technician happens to offer appliances")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "category_mismatch"


def test_slot_must_belong_to_technician(seeded, client):
    h = login(client, ASHA)
    tech, slot = first_offer(client, h)
    other = {"technician_id": tech["technician_id"] % 12 + 1}
    r = book(client, h, other, slot)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "slot_mismatch"


def test_past_slot_rejected(seeded, client):
    h = login(client, ASHA)
    tech, slot = first_offer(client, h)
    tu.freeze(tu.now() + timedelta(days=10))
    try:
        r = book(client, h, tech, slot)
    finally:
        tu.freeze(None)
    assert r.status_code == 422 and r.json()["detail"]["code"] in ("slot_in_past",)


def test_overlapping_slots_rejected_by_database(seeded):
    with new_session() as db:
        s = db.scalar(select(AvailabilitySlot).limit(1))
        clash = AvailabilitySlot(technician_id=s.technician_id, start_at=s.start_at, end_at=s.end_at)
        db.add(clash)
        with pytest.raises(IntegrityError) as exc:
            db.flush()
        assert "slots_no_overlap" in str(exc.value)


def test_non_hourly_slot_rejected_by_database(seeded):
    with new_session() as db:
        s = db.scalar(select(AvailabilitySlot).limit(1))
        bad = AvailabilitySlot(technician_id=s.technician_id, start_at=s.start_at + timedelta(days=30, minutes=15),
                               end_at=s.start_at + timedelta(days=30, minutes=75))
        db.add(bad)
        with pytest.raises(IntegrityError):
            db.flush()


# ------------------------------------------------- cancellation & slot release
def test_cancellation_releases_slot_and_keeps_history(seeded, client):
    a, r_ = login(client, ASHA), login(client, ROHAN)
    tech, slot = first_offer(client, a, days=2)
    b = book(client, a, tech, slot).json()["booking"]
    c = client.post(f"/api/bookings/{b['id']}/cancel", headers=a)
    assert c.status_code == 200 and c.json()["booking"]["status"] == "cancelled_by_customer"
    # the slot is free again for someone else
    r = book(client, r_, tech, slot)
    assert r.status_code == 201, r.text
    hist = client.get(f"/api/bookings/{b['id']}", headers=a).json()["history"]
    assert [h["to"] for h in hist] == ["confirmed", "cancelled_by_customer"]


def test_cancellation_window_enforced(seeded, client):
    h = login(client, ASHA)
    tech, slot = first_offer(client, h)
    b = book(client, h, tech, slot).json()["booking"]
    start = tu.to_local(tu.now()).fromisoformat(slot["start_at"])
    tu.freeze(start - timedelta(minutes=90))  # 1.5 h before the visit
    try:
        c = client.post(f"/api/bookings/{b['id']}/cancel", headers=h)
    finally:
        tu.freeze(None)
    assert c.status_code == 409 and c.json()["detail"]["code"] == "cancellation_window_closed"


# ------------------------------------------------------- status transitions
def _provider_for(tech_id: int) -> str:
    return provider(tech_id)  # seed creates provider NN for technician NN


def test_provider_transitions_follow_state_machine(seeded, client):
    a = login(client, ASHA)
    tech, slot = first_offer(client, a)
    b = book(client, a, tech, slot).json()["booking"]
    p = login(client, _provider_for(tech["technician_id"]))
    bad = client.post(f"/api/provider/bookings/{b['id']}/status", headers=p, json={"to_status": "completed"})
    assert bad.status_code == 409 and bad.json()["detail"]["code"] == "invalid_transition"
    for step in ("en_route", "in_progress", "completed"):
        r = client.post(f"/api/provider/bookings/{b['id']}/status", headers=p, json={"to_status": step})
        assert r.status_code == 200, r.text
    after = client.post(f"/api/provider/bookings/{b['id']}/status", headers=p, json={"to_status": "en_route"})
    assert after.status_code == 409


def test_provider_cannot_cancel_on_behalf_of_customer(seeded, client):
    a = login(client, ASHA)
    tech, slot = first_offer(client, a)
    b = book(client, a, tech, slot).json()["booking"]
    p = login(client, _provider_for(tech["technician_id"]))
    r = client.post(f"/api/provider/bookings/{b['id']}/status", headers=p, json={"to_status": "cancelled_by_customer"})
    assert r.status_code == 403


# ------------------------------------------------- roles and ownership
def test_customer_cannot_see_or_cancel_others_booking(seeded, client):
    a, r_ = login(client, ASHA), login(client, ROHAN)
    tech, slot = first_offer(client, a)
    b = book(client, a, tech, slot).json()["booking"]
    assert client.get(f"/api/bookings/{b['id']}", headers=r_).status_code == 404
    assert client.post(f"/api/bookings/{b['id']}/cancel", headers=r_).status_code == 404
    assert all(x["id"] != b["id"] for x in client.get("/api/bookings/mine", headers=r_).json()["bookings"])


def test_provider_sees_only_assigned_bookings(seeded, client):
    a = login(client, ASHA)
    tech, slot = first_offer(client, a)
    b = book(client, a, tech, slot).json()["booking"]
    other = tech["technician_id"] % 12 + 1
    p_other = login(client, provider(other))
    assert all(x["id"] != b["id"] for x in client.get("/api/provider/bookings", headers=p_other).json()["bookings"])
    r = client.post(f"/api/provider/bookings/{b['id']}/status", headers=p_other, json={"to_status": "en_route"})
    assert r.status_code == 404


def test_role_endpoints_are_enforced_on_server(seeded, client):
    a = login(client, ASHA)
    p = login(client, provider(1))
    assert client.get("/api/provider/bookings", headers=a).status_code == 403
    assert client.get("/api/bookings/mine", headers=p).status_code == 403
    assert client.get("/api/bookings/mine").status_code == 401
    assert client.get("/api/bookings/mine", headers={"Authorization": "Bearer forged.token"}).status_code == 401
    assert client.post("/api/bookings", headers={**p, "Idempotency-Key": "x"}, json={
        "slot_id": 1, "technician_id": 1, "category": "plumbing", "locality": "wakad",
        "issue_description": "x x x"}).status_code == 403


def test_admin_cannot_change_booking_status(seeded, client):
    a = login(client, ASHA)
    tech, slot = first_offer(client, a)
    b = book(client, a, tech, slot).json()["booking"]
    with new_session() as db:
        admin = db.scalar(select(User).where(User.email == ADMIN))
        with pytest.raises(svc.BookingError) as e:
            svc.change_status(db, admin, b["id"], "en_route", "", "req")
    assert e.value.http_status == 403


# ------------------------------------------------------- provider slots
def test_provider_cannot_modify_or_delete_booked_slot(seeded, client):
    a = login(client, ASHA)
    tech, slot = first_offer(client, a)
    book(client, a, tech, slot)
    p = login(client, provider(tech["technician_id"]))
    assert client.delete(f"/api/provider/slots/{slot['slot_id']}", headers=p).status_code == 409
    d = (tu.today_local() + timedelta(days=3)).isoformat()
    assert client.patch(f"/api/provider/slots/{slot['slot_id']}", headers=p,
                        json={"date": d, "hour": 7}).status_code == 409


def test_database_trigger_protects_booked_slot(seeded, client):
    a = login(client, ASHA)
    tech, slot = first_offer(client, a)
    book(client, a, tech, slot)
    with new_session() as db:
        with pytest.raises(DBAPIError) as exc:
            db.execute(text("update availability_slots set start_at = start_at + interval '1 day' where id=:s"),
                       {"s": slot["slot_id"]})
        assert "active booking" in str(exc.value)


def test_provider_can_add_and_remove_free_slot(seeded, client):
    p = login(client, provider(1))
    d = (tu.today_local() + timedelta(days=2)).isoformat()
    r = client.post("/api/provider/slots", headers=p, json={"date": d, "hour": 6})
    assert r.status_code == 201, r.text
    sid = r.json()["slot_id"]
    again = client.post("/api/provider/slots", headers=p, json={"date": d, "hour": 6})
    assert again.status_code == 409
    assert client.delete(f"/api/provider/slots/{sid}", headers=p).json()["result"] == "deleted"
