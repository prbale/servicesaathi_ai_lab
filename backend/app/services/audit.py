"""Audit logging: an append-only record of who did what, with what outcome.

Details must never contain passwords, tokens or API keys. `scrub()` removes keys that
look sensitive as a second line of defence.
"""
from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditEvent

_SENSITIVE = ("password", "token", "secret", "api_key", "authorization")


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("[redacted]" if any(s in k.lower() for s in _SENSITIVE) else scrub(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def record(
    db: Session,
    *,
    request_id: str,
    action: str,
    outcome: str,
    actor_user_id: int | None = None,
    entity_type: str = "",
    entity_id: str | int = "",
    details: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        request_id=request_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        outcome=outcome,
        details=scrub(details or {}),
    )
    db.add(event)
    db.flush()
    return event
