"""Conversational service request: free text → validated fields → matching technicians."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import User
from ..schemas import InterpretIn
from ..services import audit, extraction, matching
from ..services.ml.classifier import ModelNotTrained
from ..services.trace import Trace
from .common import finish_trace

router = APIRouter(prefix="/api/requests")


@router.post("/interpret")
def interpret(body: InterpretIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    trace = Trace(kind="service_request")
    trace.add("input", "Raw request text and user corrections", text=body.text, overrides=body.overrides,
              requested_mode=body.mode)
    try:
        with trace.step("extraction", "Extract fields with provenance (LLM if configured, else rules)") as d:
            extracted, info = extraction.extract(db, body.text, body.mode)
            d.update(method=extracted.method, method_label=extracted.method_label,
                     llm_raw_fields=info.get("llm_raw_fields"))
            if "llm_usage" in info:
                d.update(llm_usage=info["llm_usage"])
        trace.add("ml_classification", "TF-IDF + logistic regression category prediction",
                  model_version=info["ml"]["model_version"], scores=info["ml"]["scores"],
                  top_score=info["ml"]["top_score"], threshold=info["ml"]["threshold"],
                  confident=info["ml"]["confident"])
        with trace.step("validation", "Apply and validate user corrections") as d:
            extracted = extraction.apply_overrides(db, extracted, body.overrides)
            d.update(fields={f: getattr(extracted, f).model_dump() for f in extraction.FIELDS},
                     missing_fields=extracted.missing_fields)
    except ModelNotTrained as exc:
        raise HTTPException(503, str(exc)) from exc
    except extraction.OverrideError as exc:
        raise HTTPException(422, {"code": "invalid_correction", "message": str(exc)}) from exc

    search = None
    if not extracted.missing_fields:
        with trace.step("technician_matching", "Read-only SQL over technicians and free slots") as d:
            res = matching.search(db, matching.SearchCriteria(
                extracted.predicted_category.value, extracted.locality.value,
                date.fromisoformat(extracted.preferred_date.value), extracted.time_window.value))
            d.update(sql=res.sql, params=res.params, technicians_found=len(res.technicians), widened=res.widened)
        search = {"technicians": res.technicians, "widened": res.widened,
                  "charges_note": "Visiting charge only — the final repair price is quoted after diagnosis."}

    ev = audit.record(db, request_id=trace.request_id, action="request.interpret",
                      outcome="ready" if search is not None else "needs_clarification", actor_user_id=user.id,
                      details={"method": extracted.method, "missing": extracted.missing_fields})
    db.commit()
    trace.audit_ref = ev.id
    trace.outcome = ("matched " + str(len(search["technicians"])) + " technician(s)") if search is not None else \
        "asking for: " + ", ".join(extracted.missing_fields)
    return finish_trace(request, trace, user.id, {
        "extraction": extracted.model_dump(),
        "ready": search is not None,
        "search": search,
    })
