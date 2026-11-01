"""Record the trained model in the `model_versions` table (what the Admin screen shows)."""
from sqlalchemy import update

from ...db import session_scope
from ...models import ModelVersion
from . import classifier
from .train import artifact_paths


def register_saved_model() -> str | None:
    classifier.reload()
    report = classifier.get_report()
    if report is None:
        return None
    model_path, _ = artifact_paths()
    with session_scope() as db:
        db.execute(update(ModelVersion).where(ModelVersion.kind == "classifier").values(is_active=False))
        existing = db.query(ModelVersion).filter_by(kind="classifier", version=report["model_version"]).one_or_none()
        summary = {
            "threshold": report["threshold"],
            "test_accuracy": report["test"]["model"]["accuracy"],
            "test_macro_f1": report["test"]["model"]["macro_f1"],
            "baseline_accuracy": report["test"]["keyword_baseline"]["accuracy"],
            "baseline_macro_f1": report["test"]["keyword_baseline"]["macro_f1"],
            "trained_at": report["trained_at"],
        }
        if existing:
            existing.is_active = True
            existing.metrics = summary
        else:
            db.add(ModelVersion(kind="classifier", version=report["model_version"],
                                dataset_version=report["dataset_version"], artifact_path=str(model_path),
                                metrics=summary, is_active=True))
    return report["model_version"]
