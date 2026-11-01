"""Admin screens, Learning Lab endpoints, Developer Mode traces, health and failure handling."""
import io

from sqlalchemy.exc import OperationalError

from app.services.rag import ingest
from tests.conftest import ADMIN, ASHA, login, provider


def test_admin_endpoints_require_admin(seeded, client):
    a = login(client, ASHA)
    for path in ("/api/admin/technicians", "/api/admin/bookings", "/api/admin/audit", "/api/admin/documents"):
        assert client.get(path, headers=a).status_code == 403
    assert client.get("/api/admin/technicians", headers=login(client, provider(1))).status_code == 403


def test_admin_updates_technician_charges(seeded, client):
    h = login(client, ADMIN)
    t = client.get("/api/admin/technicians", headers=h).json()["technicians"][0]
    body = {**{k: t[k] for k in ("name", "bio", "years_experience", "rating", "is_active", "localities")},
            "charges": {**t["charges"], next(iter(t["charges"])): 555}}
    r = client.put(f"/api/admin/technicians/{t['id']}", headers=h, json=body)
    assert r.status_code == 200 and 555 in r.json()["charges"].values()
    bad = client.put(f"/api/admin/technicians/{t['id']}", headers=h, json={**body, "charges": {"plumbing": 0}})
    assert bad.status_code == 422


def test_admin_uploads_and_ingests_new_version(seeded, client):
    ingest.seed_policy_documents()
    h = login(client, ADMIN)
    content = ingest.read_policy_file("booking-availability.md").replace("version: 1", "version: 2")
    up = client.post("/api/admin/documents", headers=h,
                     files={"file": ("booking-availability.md", io.BytesIO(content.encode()), "text/markdown")})
    assert up.status_code == 201 and up.json()["status"] == "draft" and up.json()["version"] == 2
    res = client.post(f"/api/admin/documents/{up.json()['id']}/ingest", headers=h).json()
    assert res["status"] == "succeeded"
    docs = client.get("/api/admin/documents", headers=h).json()["documents"]
    st = {d["version"]: d["status"] for d in docs if d["doc_key"] == "booking-availability"}
    assert st == {1: "superseded", 2: "active"}
    bad = client.post("/api/admin/documents", headers=h,
                      files={"file": ("evil.pdf", io.BytesIO(b"%PDF"), "application/pdf")})
    assert bad.status_code == 422


def test_reset_requires_explicit_confirmation(seeded, client):
    h = login(client, ADMIN)
    assert client.post("/api/admin/reset", headers=h, json={"confirm": "yes"}).status_code == 422


def test_sql_lab_runs_only_catalogue_queries_read_only(seeded, client):
    h = login(client, ASHA)
    cat = client.get("/api/labs/sql/queries", headers=h).json()["queries"]
    assert len(cat) >= 5
    r = client.post("/api/labs/sql/run", headers=h, json={"query_id": "technicians_for_job",
                                                          "params": {"category": "plumbing", "locality": "wakad"}})
    assert r.status_code == 200 and r.json()["read_only"] and r.json()["rows"]
    inj = client.post("/api/labs/sql/run", headers=h, json={"query_id": "technicians_for_job",
                                                            "params": {"category": "x'; DROP TABLE users;--",
                                                                       "locality": "wakad"}})
    assert inj.status_code == 422
    assert client.post("/api/labs/sql/run", headers=h, json={"query_id": "DROP TABLE users"}).status_code == 422
    for q in cat:
        assert "email" not in q["sql"] and "password" not in q["sql"]


def test_ml_lab_shows_scores_baseline_and_features(seeded, client):
    h = login(client, ASHA)
    r = client.post("/api/labs/ml/predict", headers=h, json={"text": "the switch board is sparking"}).json()
    assert r["model"]["top_category"] == "electrical" and r["keyword_baseline"]["category"] == "electrical"
    assert r["top_features"]


def test_booking_race_lab_shows_exactly_one_winner(seeded, client):
    h = login(client, ASHA)
    r = client.post("/api/labs/booking-race", headers=h, json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert sorted(a["outcome"] for a in body["attempts"]) == ["conflict", "success"]
    assert body["active_bookings_for_slot"] == 1


def test_developer_trace_is_owned_and_safe(seeded, client):
    a, r_ = login(client, ASHA), login(client, "rohan@demo.servicesaathi.local")
    resp = client.post("/api/requests/interpret", headers=a, json={"text": "Tap leaking in Wakad tomorrow morning"})
    rid = resp.json()["request_id"]
    assert "trace" not in resp.json(), "trace only returned when Developer Mode is on"
    t = client.get(f"/api/dev/traces/{rid}", headers=a)
    assert t.status_code == 200 and t.json()["note"].startswith("Observable")
    assert client.get(f"/api/dev/traces/{rid}", headers=r_).status_code == 404
    assert "demo1234" not in t.text and "pbkdf2" not in t.text


def test_deployment_lab_never_returns_secret_values(seeded, client, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-super-secret")
    r = client.get("/api/labs/deployment", headers=login(client, ASHA))
    assert "sk-super-secret" not in r.text and r.json()["migration_revision"] == "0001"


def test_health_reports_database_and_model(seeded, client):
    r = client.get("/api/health").json()
    assert r["checks"]["database"]["ok"] and r["checks"]["database"]["pgvector"]


def test_health_reports_database_failure(client, monkeypatch):
    import app.main as main

    class Broken:
        def __enter__(self):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(main, "new_session", lambda: Broken())
    r = client.get("/api/health")
    assert r.status_code == 503 and r.json()["checks"]["database"]["ok"] is False


def test_validation_errors_are_readable(seeded, client):
    h = login(client, ASHA)
    r = client.post("/api/technicians/search", headers=h, json={"category": "carpentry", "locality": "wakad",
                                                                "preferred_date": "not-a-date"})
    assert r.status_code == 422
    fields = {e["field"] for e in r.json()["detail"]["errors"]}
    assert {"category", "preferred_date"} <= fields
