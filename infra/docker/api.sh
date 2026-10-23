#!/bin/sh
# API container: migrate, build the knowledge base (idempotent by hash), then serve.
set -e
alembic upgrade head
python scripts/build_kb.py
exec uvicorn app.api:app --host 0.0.0.0 --port 3008 --proxy-headers --forwarded-allow-ips='*'
