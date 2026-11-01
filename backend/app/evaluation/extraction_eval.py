"""Extraction field accuracy on labelled cases (data/eval/extraction_cases.jsonl).

The clock is frozen to a fixed Monday morning so relative dates are reproducible.
"""
import json
from datetime import date, datetime, timedelta, timezone

from .. import time_utils as tu
from ..config import BACKEND_DIR
from ..db import new_session
from ..services import extraction

CASES = BACKEND_DIR / "data" / "eval" / "extraction_cases.jsonl"
FROZEN_NOW = datetime(2026, 11, 2, 2, 30, tzinfo=timezone.utc)  # Mon 02 Nov 2026, 08:00 IST


def _expected_date(spec: str | None, today: date) -> str | None:
    if spec is None:
        return None
    if spec.startswith("+"):
        return (today + timedelta(days=int(spec[1:]))).isoformat()
    if spec.startswith("weekday:"):
        parts = spec.split(":")
        target = extraction.WEEKDAYS.index(parts[1])
        delta = (target - today.weekday()) % 7
        if delta == 0 and len(parts) > 2 and parts[2] == "next":
            delta = 7
        return (today + timedelta(days=delta)).isoformat()
    if spec.startswith("abs:"):
        return f"{today.year}-{spec[4:]}"
    return spec


def run(mode: str = "rules") -> dict:
    cases = [json.loads(line) for line in CASES.read_text().splitlines() if line.strip()]
    tu.freeze(FROZEN_NOW)
    try:
        today = tu.today_local()
        per_field = {f: {"correct": 0, "total": 0} for f in
                     ("predicted_category", "locality", "preferred_date", "time_window", "issue_present",
                      "safety_notice", "missing_fields")}
        failures = []
        methods = set()
        with new_session() as db:
            for case in cases:
                got, _ = extraction.extract(db, case["text"], mode)
                methods.add(got.method_label)
                exp = case["expect"]
                actual = {
                    "predicted_category": got.predicted_category.value,
                    "locality": got.locality.value,
                    "preferred_date": got.preferred_date.value,
                    "time_window": got.time_window.value,
                    "issue_present": got.issue_description.value is not None,
                    "safety_notice": got.safety_notice is not None,
                }
                expected = {k: (_expected_date(v, today) if k == "preferred_date" else v) for k, v in exp.items()}
                case_fail = {}
                for field, want in expected.items():
                    per_field[field]["total"] += 1
                    if actual[field] == want:
                        per_field[field]["correct"] += 1
                    else:
                        case_fail[field] = {"expected": want, "got": actual[field]}
                options = case.get("expect_missing_any_of") or [case.get("expect_missing", [])]
                per_field["missing_fields"]["total"] += 1
                if any(sorted(got.missing_fields) == sorted(o) for o in options):
                    per_field["missing_fields"]["correct"] += 1
                else:
                    case_fail["missing_fields"] = {"expected": options, "got": got.missing_fields}
                if case_fail:
                    failures.append({"id": case["id"], "text": case["text"], "fields": case_fail})
    finally:
        tu.freeze(None)
    acc = {f: round(v["correct"] / v["total"], 4) if v["total"] else None for f, v in per_field.items()}
    totals = sum(v["correct"] for v in per_field.values()), sum(v["total"] for v in per_field.values())
    return {
        "summary": {"cases": len(cases), "fully_correct_cases": len(cases) - len(failures),
                    "field_accuracy": acc, "overall_field_accuracy": round(totals[0] / totals[1], 4),
                    "method": sorted(methods), "frozen_today": today.isoformat()},
        "failures": failures,
    }
