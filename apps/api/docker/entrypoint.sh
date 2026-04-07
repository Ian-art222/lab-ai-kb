#!/bin/sh
set -eu

cd /app/apps/api

WAIT_DB_URL="${DATABASE_URL}"
case "${WAIT_DB_URL}" in
  postgresql+psycopg://*)
    WAIT_DB_URL="postgresql://${WAIT_DB_URL#postgresql+psycopg://}"
    ;;
esac

PG_WAIT_URL="${PG_WAIT_URL:-$WAIT_DB_URL}"
export PG_WAIT_URL

python - <<'PY'
import os
import time
import psycopg

url = os.environ["PG_WAIT_URL"]
max_attempts = 60
for attempt in range(1, max_attempts + 1):
    try:
        with psycopg.connect(url):
            print("Database is ready")
            break
    except Exception as exc:
        if attempt == max_attempts:
            raise
        print(f"Waiting for database ({attempt}/{max_attempts}): {exc}")
        time.sleep(2)
PY

alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
