#!/bin/sh
# Container entrypoint: migrate -> prepare (train/seed if needed) -> serve.
set -e
cd "$(dirname "$0")/.."
echo "[start] applying migrations"
alembic upgrade head
echo "[start] preparing model and demo data"
python -m app.bootstrap
echo "[start] serving on :8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers
