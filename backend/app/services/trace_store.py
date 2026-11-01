"""Keeps the most recent traces in memory so Developer Mode can fetch them by request ID.

Memory-only by design: traces are a debugging aid, not business records (the durable
record is `audit_events`). Each trace is visible only to the user who caused it, or admins.
"""
from collections import OrderedDict
from threading import Lock

_MAX = 300
_store: "OrderedDict[str, tuple[int | None, dict]]" = OrderedDict()
_lock = Lock()


def put(owner_user_id: int | None, trace: dict) -> None:
    with _lock:
        _store[trace["request_id"]] = (owner_user_id, trace)
        while len(_store) > _MAX:
            _store.popitem(last=False)


def get(request_id: str, user_id: int, is_admin: bool) -> dict | None:
    with _lock:
        item = _store.get(request_id)
    if item is None:
        return None
    owner, trace = item
    if is_admin or owner == user_id:
        return trace
    return None


def recent(user_id: int, is_admin: bool, limit: int = 20) -> list[dict]:
    with _lock:
        items = list(_store.values())[::-1]
    out = [t for owner, t in items if is_admin or owner == user_id]
    return [{"request_id": t["request_id"], "kind": t["kind"], "outcome": t["outcome"]} for t in out[:limit]]
