#!/bin/sh
# Container entrypoint: migrate -> prepare (train/seed if needed) -> serve.
set -e
cd "$(dirname "$0")/.."
echo "[start] applying migrations"
alembic upgrade head
echo "[start] preparing model and demo data"
python -m app.bootstrap
PORT="${PORT:-8000}"
echo "[start] serving on :$PORT"
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --proxy-headers
