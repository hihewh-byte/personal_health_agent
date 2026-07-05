#!/bin/sh
set -e

cd /app
export PYTHONPATH=/app

echo "==> PHA Docker entrypoint"
python scripts/doctor.py --quick || true

HOST="${PHA_HOST:-0.0.0.0}"
PORT="${PHA_PORT:-8788}"

echo "==> Starting uvicorn on ${HOST}:${PORT}"
exec python -m uvicorn pha.main:app --host "${HOST}" --port "${PORT}"
