"""Customer policy questions with cited answers."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import User
from ..schemas import PolicyQuestionIn
from ..services import audit
from ..services.rag.answer import answer_question
from ..services.trace import Trace
from .common import finish_trace

router = APIRouter(prefix="/api/policy")


@router.post("/ask")
def ask(body: PolicyQuestionIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    trace = Trace(kind="policy_question")
    trace.add("input", "Validated question", question=body.question)
    out = answer_question(db, body.question, user, trace)
    ev = audit.record(db, request_id=trace.request_id, action="policy.ask", outcome=out["mode"],
                      actor_user_id=user.id, details={"route": out["route"], "citations": len(out["citations"])})
    db.commit()
    trace.audit_ref = ev.id
    trace.outcome = f"{out['mode']} ({out['route']})"
    return finish_trace(request, trace, user.id, out)
