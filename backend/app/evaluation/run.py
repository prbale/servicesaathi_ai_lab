"""Run evaluation suites and store results in `evaluation_runs`.

    python -m app.evaluation.run                 # all suites
    python -m app.evaluation.run --suite policy  # one suite

Suites
  ml          held-out classifier metrics vs keyword baseline (re-computed from the saved report)
  extraction  field accuracy on labelled requests
  retrieval   recall@k against labelled relevant sections
  policy      30+ policy questions: answered/abstained/routed, citation validity, injection resistance

Automated metrics only. Human-reviewed answer quality is tracked separately in
docs/evaluation-report.md and is never auto-filled.
"""
import argparse
import json
import traceback

from .. import time_utils as tu
from ..db import session_scope
from ..models import EvaluationRun

SUITES = ("ml", "extraction", "retrieval", "policy")


def _suite(name: str) -> dict:
    if name == "ml":
        from ..services.ml import classifier

        r = classifier.get_report()
        if r is None:
            raise RuntimeError("No trained model. Run python -m app.services.ml.train")
        m, b, s = r["test"]["model"], r["test"]["keyword_baseline"], r["test"]["model_with_threshold"]
        return {"summary": {"model_version": r["model_version"], "dataset_version": r["dataset_version"],
                            "model": {k: m[k] for k in ("accuracy", "macro_f1")},
                            "keyword_baseline": {k: b[k] for k in ("accuracy", "macro_f1")},
                            "threshold": r["threshold"], "coverage": s["in_scope"]["coverage"],
                            "selective_accuracy": s["in_scope"]["selective_accuracy"],
                            "out_of_scope_asked": f"{s['out_of_scope']['asked_user']}/{s['out_of_scope']['n']}",
                            "ambiguous_asked": f"{s['ambiguous']['asked_user']}/{s['ambiguous']['n']}",
                            "caveats": r["caveats"]},
                "failures": [e for e in s["out_of_scope"]["examples"] if not e["asked_user"]]
                + [e for e in s["ambiguous"]["examples"] if not e["asked_user"] and e["top"] not in e["acceptable"]]}
    if name == "extraction":
        from . import extraction_eval

        return extraction_eval.run("rules")
    if name in ("retrieval", "policy"):
        from . import policy_eval

        return policy_eval.run_retrieval() if name == "retrieval" else policy_eval.run_policy()
    raise ValueError(name)


def run_suite(name: str) -> dict:
    with session_scope() as db:
        run = EvaluationRun(suite=name, status="running", config={})
        db.add(run)
        db.flush()
        run_id = run.id
    try:
        result = _suite(name)
        status, error = "succeeded", None
    except Exception as exc:  # recorded honestly, never hidden
        result, status, error = {"summary": {}, "failures": []}, "failed", f"{exc}\n{traceback.format_exc()[-800:]}"
    with session_scope() as db:
        run = db.get(EvaluationRun, run_id)
        run.status, run.summary, run.failures, run.error = status, result["summary"], result["failures"], error
        run.finished_at = tu.now()
    return {"id": run_id, "suite": name, "status": status, "summary": result["summary"],
            "failures": result["failures"], "error": error}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", choices=SUITES + ("all",), default="all")
    args = ap.parse_args()
    for s in SUITES if args.suite == "all" else (args.suite,):
        out = run_suite(s)
        print(f"\n=== {s}: {out['status']} (run #{out['id']}) ===")
        print(json.dumps(out["summary"], indent=2, default=str))
        print(f"failures: {len(out['failures'])}")
        if out["error"]:
            print(out["error"])
