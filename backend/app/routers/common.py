"""Shared router helpers."""
from fastapi import Request

from ..services import trace_store
from ..services.trace import Trace


def dev_mode(request: Request) -> bool:
    return request.headers.get("x-developer-mode") == "1"


def finish_trace(request: Request, trace: Trace, user_id: int | None, payload: dict) -> dict:
    """Store the trace and attach it to the response only when Developer Mode is on."""
    t = trace.to_dict()
    trace_store.put(user_id, t)
    payload["request_id"] = trace.request_id
    if dev_mode(request):
        payload["trace"] = t
    return payload
