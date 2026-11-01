"""Idempotent startup preparation used by scripts/start.sh and Docker.

    python -m app.bootstrap

1. Train the classifier if no saved model exists (takes a few seconds).
2. Seed demo data only if the database is empty (never wipes existing bookings).
3. Make sure the trained model is registered in model_versions.
"""
from sqlalchemy import text

from .db import session_scope
from .seed import seed_all
from .services.ml import classifier
from .services.ml.registry import register_saved_model


def main() -> None:
    if classifier.get_model_info() is None:
        from .services.ml.train import train

        r = train()
        classifier.reload()
        print(f"[bootstrap] trained {r['model_version']}")
    with session_scope() as db:
        empty = db.execute(text("SELECT count(*) FROM technicians")).scalar() == 0
    if empty:
        print("[bootstrap] empty database — seeding demo data:", seed_all())
    else:
        print("[bootstrap] existing data kept; model registered:", register_saved_model())


if __name__ == "__main__":
    main()
