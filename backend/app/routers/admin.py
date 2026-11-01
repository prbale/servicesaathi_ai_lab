"""Admin: directory management, policy documents, inspection, demo reset."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import time_utils as tu
from ..auth import require_role
from ..db import get_db
from ..models import (
    AuditEvent,
    Booking,
    DocumentChunk,
    EvaluationRun,
    Locality,
    ModelVersion,
    PolicyDocument,
    ServiceCategory,
    Technician,
    TechnicianCategory,
    TechnicianServiceArea,
    User,
)
from ..schemas import CategoryUpdateIn, LocalityIn, ResetIn, TechnicianIn
from ..services import audit, booking
from ..services.rag import chunking, ingest
from ..services.trace import new_request_id

router = APIRouter(prefix="/api/admin")
admin_only = require_role("admin")


def tech_dict(t: Technician) -> dict:
    return {"id": t.id, "name": t.name, "bio": t.bio, "years_experience": t.years_experience,
            "rating": float(t.rating), "is_active": t.is_active,
            "charges": {c.category_code: c.visiting_charge_inr for c in t.categories},
            "localities": sorted(a.locality_code for a in t.areas)}


@router.get("/technicians")
def technicians(_: User = Depends(admin_only), db: Session = Depends(get_db)):
    return {"technicians": [tech_dict(t) for t in db.scalars(select(Technician).order_by(Technician.id))]}


def _apply(t: Technician, body: TechnicianIn, db: Session):
    valid_locs = set(db.scalars(select(Locality.code)))
    bad = [loc for loc in body.localities if loc not in valid_locs]
    if bad:
        raise HTTPException(422, f"Unknown localities: {bad}")
    t.name, t.bio, t.years_experience, t.rating, t.is_active = (body.name, body.bio, body.years_experience,
                                                                body.rating, body.is_active)
    existing = {c.category_code: c for c in t.categories}
    t.categories = [existing.get(code) or TechnicianCategory(category_code=code, visiting_charge_inr=amount)
                    for code, amount in body.charges.items()]
    for c in t.categories:
        c.visiting_charge_inr = body.charges[c.category_code]
    existing_areas = {a.locality_code: a for a in t.areas}
    t.areas = [existing_areas.get(code) or TechnicianServiceArea(locality_code=code) for code in body.localities]


@router.post("/technicians", status_code=201)
def create_technician(body: TechnicianIn, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    t = Technician()
    db.add(t)
    _apply(t, body, db)
    db.flush()
    audit.record(db, request_id=new_request_id(), action="admin.technician.create", outcome="success",
                 actor_user_id=user.id, entity_type="technician", entity_id=t.id)
    db.commit()
    return tech_dict(t)


@router.put("/technicians/{tech_id}")
def update_technician(tech_id: int, body: TechnicianIn, user: User = Depends(admin_only),
                      db: Session = Depends(get_db)):
    t = db.get(Technician, tech_id)
    if t is None:
        raise HTTPException(404, "Technician not found.")
    _apply(t, body, db)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This technician has bookings for a category or locality you removed. "
                                 "Keep it, or deactivate the technician instead.") from exc
    audit.record(db, request_id=new_request_id(), action="admin.technician.update", outcome="success",
                 actor_user_id=user.id, entity_type="technician", entity_id=t.id, details=body.model_dump())
    db.commit()
    return tech_dict(t)


@router.get("/categories")
def categories(_: User = Depends(admin_only), db: Session = Depends(get_db)):
    return {"categories": [{"code": c.code, "name": c.name, "description": c.description}
                           for c in db.scalars(select(ServiceCategory).order_by(ServiceCategory.code))],
            "note": "The three category codes are fixed because the ML model is trained on them. "
                    "Adding a category needs new training data and retraining."}


@router.put("/categories/{code}")
def update_category(code: str, body: CategoryUpdateIn, user: User = Depends(admin_only),
                    db: Session = Depends(get_db)):
    c = db.get(ServiceCategory, code)
    if c is None:
        raise HTTPException(404, "Category not found.")
    c.name, c.description = body.name, body.description
    audit.record(db, request_id=new_request_id(), action="admin.category.update", outcome="success",
                 actor_user_id=user.id, entity_type="category", entity_id=code)
    db.commit()
    return {"code": c.code, "name": c.name, "description": c.description}


@router.get("/localities")
def localities(_: User = Depends(admin_only), db: Session = Depends(get_db)):
    return {"localities": [{"code": loc.code, "name": loc.name, "aliases": loc.aliases}
                           for loc in db.scalars(select(Locality).order_by(Locality.name))]}


@router.post("/localities", status_code=201)
def add_locality(body: LocalityIn, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    db.add(Locality(code=body.code, name=body.name, aliases=[a.strip().lower() for a in body.aliases if a.strip()]))
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "A locality with that code or name already exists.") from exc
    audit.record(db, request_id=new_request_id(), action="admin.locality.create", outcome="success",
                 actor_user_id=user.id, entity_type="locality", entity_id=body.code)
    db.commit()
    return body.model_dump()


# ------------------------------------------------------------------ documents
@router.get("/documents")
def documents(_: User = Depends(admin_only), db: Session = Depends(get_db)):
    rows = db.scalars(select(PolicyDocument).order_by(PolicyDocument.doc_key, PolicyDocument.version.desc()))
    return {"documents": [ingest.document_dict(d) for d in rows]}


@router.post("/documents", status_code=201)
async def upload_document(file: UploadFile = File(...), doc_key: str = Form(""), title: str = Form(""),
                          user: User = Depends(admin_only), db: Session = Depends(get_db)):
    name = file.filename or ""
    if not name.lower().endswith((".md", ".txt", ".markdown")):
        raise HTTPException(422, "Only plain-text (.txt) or Markdown (.md) files are accepted.")
    raw = await file.read()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "File must be UTF-8 text.") from exc
    try:
        doc = ingest.upload(db, content, filename=name, uploaded_by=user.id, fallback_key=doc_key.strip(),
                            fallback_title=title.strip())
    except chunking.DocumentFormatError as exc:
        raise HTTPException(422, str(exc)) from exc
    audit.record(db, request_id=new_request_id(), action="admin.document.upload", outcome="success",
                 actor_user_id=user.id, entity_type="policy_document", entity_id=doc.id,
                 details={"doc_key": doc.doc_key, "version": doc.version})
    db.commit()
    return ingest.document_dict(doc)


@router.post("/documents/{doc_id}/ingest")
def ingest_document(doc_id: int, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    if db.get(PolicyDocument, doc_id) is None:
        raise HTTPException(404, "Document not found.")
    result = ingest.ingest(doc_id)
    audit.record(db, request_id=new_request_id(), action="admin.document.ingest", outcome=result["status"],
                 actor_user_id=user.id, entity_type="policy_document", entity_id=doc_id, details=result)
    db.commit()
    return result


@router.get("/documents/{doc_id}/chunks")
def document_chunks(doc_id: int, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    rows = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == doc_id)
                      .order_by(DocumentChunk.chunk_index))
    return {"chunks": [{"index": c.chunk_index, "section": c.section_title, "content": c.content,
                        "quarantined": c.is_quarantined, "reason": c.quarantine_reason} for c in rows]}


# ------------------------------------------------------------------ inspection
@router.get("/bookings")
def all_bookings(_: User = Depends(admin_only), db: Session = Depends(get_db)):
    rows = db.scalars(select(Booking).order_by(Booking.id.desc()).limit(200)).all()
    out = []
    for b in rows:
        d = booking.booking_to_dict(db, b)
        cust = db.get(User, b.customer_id)
        d["customer"] = cust.display_name if cust else None  # display name only, no email
        out.append(d)
    return {"bookings": out}


@router.get("/model-versions")
def model_versions(_: User = Depends(admin_only), db: Session = Depends(get_db)):
    rows = db.scalars(select(ModelVersion).order_by(ModelVersion.id.desc()))
    return {"model_versions": [{"kind": m.kind, "version": m.version, "dataset_version": m.dataset_version,
                                "is_active": m.is_active, "metrics": m.metrics,
                                "created_at": tu.to_local(m.created_at).isoformat()} for m in rows]}


@router.get("/evaluations")
def evaluations(_: User = Depends(admin_only), db: Session = Depends(get_db)):
    rows = db.scalars(select(EvaluationRun).order_by(EvaluationRun.id.desc()).limit(50))
    return {"runs": [run_dict(r) for r in rows]}


def run_dict(r: EvaluationRun) -> dict:
    return {"id": r.id, "suite": r.suite, "status": r.status, "summary": r.summary, "failures": r.failures,
            "error": r.error, "started_at": tu.to_local(r.started_at).isoformat() if r.started_at else None,
            "finished_at": tu.to_local(r.finished_at).isoformat() if r.finished_at else None}


@router.get("/audit")
def audit_events(limit: int = 100, _: User = Depends(admin_only), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(min(limit, 500)))
    return {"events": [{"id": e.id, "request_id": e.request_id, "actor_user_id": e.actor_user_id,
                        "action": e.action, "entity": f"{e.entity_type}:{e.entity_id}" if e.entity_type else "",
                        "outcome": e.outcome, "details": e.details,
                        "at": tu.to_local(e.created_at).isoformat()} for e in rows]}


@router.post("/reset")
def reset(body: ResetIn, _: User = Depends(admin_only)):
    if body.confirm != "RESET":
        raise HTTPException(422, "Type RESET to confirm. This deletes all bookings and restores demo data.")
    from ..seed import seed_all

    summary = seed_all(with_policies=True, with_model=True)
    from ..db import session_scope

    with session_scope() as db:
        audit.record(db, request_id=new_request_id(), action="admin.demo_reset", outcome="success",
                     details=summary)
    return {"reset": True, "summary": summary,
            "note": "All accounts were re-created with the same demo passwords. Please sign in again."}
