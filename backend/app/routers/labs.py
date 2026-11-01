"""Learning Lab endpoints and Developer Mode traces. Each lab works on its own."""
import os
import threading
import time
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import time_utils as tu
from ..auth import current_user
from ..config import get_settings
from ..db import get_db, new_session
from ..models import (
    ACTIVE_BOOKING_STATUSES,
    AvailabilitySlot,
    Booking,
    BookingStatusEvent,
    DocumentChunk,
    EvaluationRun,
    PolicyDocument,
    TechnicianCategory,
    TechnicianServiceArea,
    User,
)
from ..services import booking, extraction, sql_lab, trace_store
from ..services.llm import providers
from ..services.ml import classifier
from ..services.rag.answer import answer_question
from ..services.rag.retrieval import retrieve
from ..services.trace import Trace
from .admin import run_dict

router = APIRouter(prefix="/api")


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class SqlRunIn(BaseModel):
    query_id: str
    params: dict[str, str] = Field(default_factory=dict)
    explain: bool = False


class RagQueryIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    k: int = Field(default=5, ge=1, le=10)


class RaceIn(BaseModel):
    slot_id: int | None = None


class EvalIn(BaseModel):
    suite: str = Field(pattern="^(ml|extraction|retrieval|policy)$")


# ------------------------------------------------------------------ SQL lab
@router.get("/labs/sql/queries")
def sql_queries(_: User = Depends(current_user)):
    return {"queries": sql_lab.catalogue()}


@router.post("/labs/sql/run")
def sql_run(body: SqlRunIn, _: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        return sql_lab.run(db, body.query_id, body.params, body.explain)
    except sql_lab.SqlLabError as exc:
        raise HTTPException(422, str(exc)) from exc


# ------------------------------------------------------------------ ML lab
@router.post("/labs/ml/predict")
def ml_predict(body: TextIn, _: User = Depends(current_user)):
    try:
        out = classifier.compare(body.text)
    except classifier.ModelNotTrained as exc:
        raise HTTPException(503, str(exc)) from exc
    out["top_features"] = classifier.explain(body.text)
    return out


@router.get("/labs/ml/report")
def ml_report(_: User = Depends(current_user)):
    r = classifier.get_report()
    if r is None:
        raise HTTPException(404, "No training report yet. Run: python -m app.services.ml.train")
    return r


# ------------------------------------------------------------------ extraction lab
@router.post("/labs/extraction")
def extraction_lab(body: TextIn, _: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        rules, _info = extraction.extract(db, body.text, "rules")
    except classifier.ModelNotTrained as exc:
        raise HTTPException(503, str(exc)) from exc
    out = {"rules": rules.model_dump(), "llm": None, "llm_status": "not configured"}
    if get_settings().llm_enabled:
        try:
            llm, info = extraction.llm_extract(db, body.text)
            out["llm"], out["llm_status"] = llm.model_dump(), "ok"
            out["llm_raw"], out["llm_usage"] = info.get("llm_raw_fields"), info.get("llm_usage")
        except providers.LLMUnavailable as exc:
            out["llm_status"] = f"failed: {exc}"
    return out


# ------------------------------------------------------------------ RAG lab
@router.get("/labs/rag/chunks")
def rag_chunks(_: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(PolicyDocument.title, PolicyDocument.version, PolicyDocument.status,
                             DocumentChunk.id, DocumentChunk.chunk_index, DocumentChunk.section_title,
                             DocumentChunk.content, DocumentChunk.is_quarantined, DocumentChunk.embedding_model)
                      .join(PolicyDocument, PolicyDocument.id == DocumentChunk.document_id)
                      .order_by(PolicyDocument.doc_key, PolicyDocument.version, DocumentChunk.chunk_index)).all()
    return {"chunks": [{"title": r[0], "version": r[1], "doc_status": r[2], "chunk_id": r[3], "index": r[4],
                        "section": r[5], "content": r[6], "quarantined": r[7], "embedding_model": r[8]}
                       for r in rows]}


@router.post("/labs/rag/query")
def rag_query(body: RagQueryIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    passages, info = retrieve(db, body.question, body.k)
    db.rollback()
    trace = Trace(kind="rag_lab")
    out = answer_question(db, body.question, user, trace)
    return {"retrieval": {**info, "threshold": get_settings().rag_min_similarity,
                          "passages": [p.to_dict() for p in passages]},
            "answer": out, "trace": trace.to_dict()}


# ------------------------------------------------------------------ booking rules lab
def _pick_free_slot(db: Session) -> AvailabilitySlot:
    start = tu.now() + timedelta(hours=3)  # far enough ahead that lab cleanup can cancel within policy
    active_exists = select(Booking.id).where(Booking.slot_id == AvailabilitySlot.id,
                                             Booking.status.in_(ACTIVE_BOOKING_STATUSES)).exists()
    slot = db.scalar(select(AvailabilitySlot).where(AvailabilitySlot.start_at > start,
                                                    AvailabilitySlot.is_withdrawn.is_(False), ~active_exists)
                     .order_by(AvailabilitySlot.start_at).limit(1))
    if slot is None:
        raise HTTPException(409, "No free future slot is available for the simulation. Reset the demo data.")
    return slot


@router.post("/labs/booking-race")
def booking_race(body: RaceIn, _: User = Depends(current_user), db: Session = Depends(get_db)):
    """Two lab customers confirm the SAME slot at the same instant, through the real booking service."""
    slot = db.get(AvailabilitySlot, body.slot_id) if body.slot_id else _pick_free_slot(db)
    if slot is None:
        raise HTTPException(404, "Slot not found.")
    cat = db.scalar(select(TechnicianCategory.category_code).where(TechnicianCategory.technician_id == slot.technician_id))
    loc = db.scalar(select(TechnicianServiceArea.locality_code)
                    .where(TechnicianServiceArea.technician_id == slot.technician_id))
    emails = [f"lab.racer.{x}@demo.servicesaathi.local" for x in "ab"]
    racer_ids = [db.scalar(select(User.id).where(User.email == e)) for e in emails]
    slot_id, tech_id, slot_label = slot.id, slot.technician_id, tu.fmt_local(slot.start_at)
    db.rollback()

    barrier = threading.Barrier(2)
    results: list[dict] = [{}, {}]

    def attempt(i: int):
        s = new_session()  # each racer has its own session/connection, like two separate web requests
        req = booking.BookingRequest(slot_id, tech_id, cat, loc, "Booking Rules Lab simulation")
        racer = s.get(User, racer_ids[i])
        t0 = None
        try:
            barrier.wait()
            t0 = time.perf_counter()
            b, _ = booking.create_booking(s, racer, req, f"lab-{uuid.uuid4()}", f"lab_race_{i}")
            results[i] = {"racer": "AB"[i], "outcome": "success", "reference": b["reference"]}
        except booking.BookingError as err:
            results[i] = {"racer": "AB"[i], "outcome": "conflict" if err.http_status == 409 else "rejected",
                          "code": err.code, "message": err.message,
                          "alternatives_offered": len(err.details.get("alternatives", []))}
        finally:
            results[i]["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1) if t0 else None
            results[i]["checks"] = req.checks
            s.close()

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    rows = db.execute(text("SELECT reference, status, customer_id FROM bookings WHERE slot_id = :s ORDER BY id"),
                      {"s": slot_id}).all()
    db_state = [{"reference": r[0], "status": r[1], "racer": "A" if r[2] == racer_ids[0] else
                 "B" if r[2] == racer_ids[1] else "other"} for r in rows]
    # Clean up: cancel the lab booking so the slot is released (history is kept).
    winner = db.scalar(select(Booking).where(Booking.slot_id == slot_id, Booking.status == "confirmed",
                                             Booking.customer_id.in_(racer_ids)))
    if winner:
        winner.status = "cancelled_by_customer"
        db.add(BookingStatusEvent(booking_id=winner.id, from_status="confirmed", to_status="cancelled_by_customer",
                                  actor_user_id=winner.customer_id, reason="Booking Rules Lab cleanup"))
        db.commit()
    return {"slot": {"slot_id": slot_id, "technician_id": tech_id, "label": slot_label},
            "attempts": results, "database_rows_for_slot": db_state,
            "active_bookings_for_slot": sum(r["status"] in ACTIVE_BOOKING_STATUSES for r in db_state),
            "cleanup": "Winning lab booking cancelled afterwards so the slot is free again; history kept."}


# ------------------------------------------------------------------ evaluation lab
@router.post("/labs/evaluations/run")
def eval_run(body: EvalIn, _: User = Depends(current_user)):
    from ..evaluation.run import run_suite

    return run_suite(body.suite)


@router.get("/labs/evaluations")
def eval_latest(_: User = Depends(current_user), db: Session = Depends(get_db)):
    latest = {}
    for r in db.scalars(select(EvaluationRun).order_by(EvaluationRun.id.desc()).limit(100)):
        latest.setdefault(r.suite, run_dict(r))
    return {"latest": latest}


# ------------------------------------------------------------------ deployment lab
ENV_VARS = ["DATABASE_URL", "APP_SECRET", "LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL",
            "EMBEDDING_PROVIDER", "EMBEDDING_MODEL", "EMBEDDING_API_KEY", "RAG_MIN_SIMILARITY", "RAG_TOP_K",
            "MODEL_DIR", "DISPLAY_TIMEZONE"]


@router.get("/labs/deployment")
def deployment(_: User = Depends(current_user), db: Session = Depends(get_db)):
    s = get_settings()
    rev = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    secrets_default = s.app_secret == "change-me-local-demo-secret"
    return {
        "environment": [{"name": n, "set": n in os.environ,
                         "value": None if any(x in n for x in ("KEY", "SECRET", "URL")) else os.environ.get(n)}
                        for n in ENV_VARS],
        "warnings": ["APP_SECRET is the built-in default — change it outside local demos."] if secrets_default else [],
        "migration_revision": rev,
        "model": classifier.get_model_info(),
        "model_dir": s.model_dir,
        "embedding": providers.embedding_info(),
        "llm": {"configured": s.llm_enabled, "provider": s.llm_provider if s.llm_enabled else "none"},
        "running_in_container": os.path.exists("/.dockerenv"),
        "note": "Secret values are never returned — only whether they are set.",
    }


# ------------------------------------------------------------------ developer mode
SCENARIOS = [
    {"id": "happy", "label": "Leaking tap, all details", "kind": "request",
     "text": "My kitchen tap is leaking. I need a plumber tomorrow morning in Wakad."},
    {"id": "missing", "label": "Missing area and time", "kind": "request", "text": "Washing machine is not spinning"},
    {"id": "unsupported_area", "label": "Unsupported area", "kind": "request",
     "text": "MCB keeps tripping. I am in Kothrud, can you come tomorrow afternoon?"},
    {"id": "hazard", "label": "Electrical hazard", "kind": "request",
     "text": "Burning smell and sparks from the switch board in Baner, today evening"},
    {"id": "vague", "label": "Vague request", "kind": "request", "text": "Something is wrong in the kitchen"},
    {"id": "policy", "label": "Policy: cancellation", "kind": "policy", "text": "How late can I cancel my booking?"},
    {"id": "abstain", "label": "Policy: unsupported", "kind": "policy", "text": "Do you offer car washing?"},
    {"id": "live", "label": "Live availability", "kind": "policy",
     "text": "Are there any plumbers available tomorrow in Wakad?"},
]


@router.get("/dev/scenarios")
def scenarios(_: User = Depends(current_user)):
    return {"scenarios": SCENARIOS}


@router.get("/dev/traces")
def traces(user: User = Depends(current_user)):
    return {"traces": trace_store.recent(user.id, user.role == "admin")}


@router.get("/dev/traces/{request_id}")
def trace(request_id: str, user: User = Depends(current_user)):
    t = trace_store.get(request_id, user.id, user.role == "admin")
    if t is None:
        raise HTTPException(404, "Trace not found (traces are kept in memory for recent requests only).")
    return t
