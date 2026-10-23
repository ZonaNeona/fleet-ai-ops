"""First install: isolated PostgreSQL role and database plus /etc/fleet.env. Secrets are never printed.

The OpenRouter key is added to /etc/fleet.env by hand afterwards (OPENROUTER_API_KEY=...).
"""

import grp
import os
import secrets
import subprocess
from pathlib import Path

env = Path(os.getenv("FLEET_ENV", "/etc/fleet.env"))


def sql(query, db="postgres"):
    return subprocess.run(
        ["runuser", "-u", "postgres", "--", "psql", "-d", db, "-v", "ON_ERROR_STOP=1", "-Atc", query],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


if not env.exists():
    pwd = secrets.token_hex(24)
    if sql("SELECT 1 FROM pg_roles WHERE rolname='fleet'"):
        raise SystemExit("Role already exists without app env; inspect before replacing credentials")
    sql(f"CREATE ROLE fleet LOGIN PASSWORD '{pwd}'")
    if not sql("SELECT 1 FROM pg_database WHERE datname='fleet'"):
        sql("CREATE DATABASE fleet OWNER fleet")
    sql("CREATE EXTENSION IF NOT EXISTS btree_gist", db="fleet")
    sql("CREATE EXTENSION IF NOT EXISTS vector", db="fleet")
    values = {
        "DATABASE_URL": f"postgresql+psycopg://fleet:{pwd}@127.0.0.1/fleet",
        "PUBLIC_URL": "https://fleet.example.com",
        "DAILY_BUDGET": "0.50",
        "TEXT_MODELS": "deepseek/deepseek-v4.1-flash,qwen/qwen3.8-flash",
        "VISION_MODEL": "google/gemini-2.5-flash-lite",
        "TELEGRAM_WEBHOOK_SECRET": secrets.token_urlsafe(32),
    }
    env.write_text("\n".join(k + "=" + str(v) for k, v in values.items()) + "\n")
    os.chown(env, 0, grp.getgrnam("fleet").gr_gid)
    os.chmod(env, 0o640)
print("Isolated database and environment configured; secrets not displayed")
