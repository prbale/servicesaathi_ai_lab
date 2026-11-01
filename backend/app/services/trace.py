"""Execution traces for Developer Mode.

A Trace records *observable* processing evidence — inputs, validated fields, which
component ran, how long it took, what it returned. It never records hidden reasoning,
secrets, passwords or raw tokens.
"""
import time
import uuid
from contextlib import contextmanager
from typing import Any

from .audit import scrub


def new_request_id() -> str:
    return "req_" + uuid.uuid4().hex[:12]


class Trace:
    def __init__(self, request_id: str | None = None, kind: str = ""):
        self.request_id = request_id or new_request_id()
        self.kind = kind
        self.steps: list[dict[str, Any]] = []
        self._t0 = time.perf_counter()
        self.outcome: str | None = None
        self.audit_ref: int | None = None

    @contextmanager
    def step(self, component: str, description: str = ""):
        """Time a component. Inside, call `data.update(...)` to attach evidence."""
        data: dict[str, Any] = {}
        start = time.perf_counter()
        error = None
        try:
            yield data
        except Exception as exc:  # recorded, then re-raised
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self.steps.append(
                {
                    "component": component,
                    "description": description,
                    "latency_ms": round((time.perf_counter() - start) * 1000, 2),
                    "data": scrub(data),
                    **({"error": error} if error else {}),
                }
            )

    def add(self, component: str, description: str = "", **data: Any) -> None:
        self.steps.append({"component": component, "description": description, "latency_ms": None, "data": scrub(data)})

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "kind": self.kind,
            "total_latency_ms": round((time.perf_counter() - self._t0) * 1000, 2),
            "steps": self.steps,
            "outcome": self.outcome,
            "audit_ref": self.audit_ref,
            "note": "Observable processing evidence only — not hidden model reasoning.",
        }
