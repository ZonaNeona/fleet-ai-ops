#!/usr/bin/env bash
# Deploys an archive made by scripts/pack.sh. Run as root on the host:
#   bash deploy.sh /tmp/fleet-release.tar.gz [--kb] [--quality]
# Snapshot and backup first, keep old lazy chunks for open tabs, migrate, restart, health check.
# --kb rebuilds the knowledge base after app/kb edits (loads the embedding model, ~1 min).
# --quality measures the release for «Код и качество»: tests with coverage on a throwaway database, ruff, mypy.
set -euo pipefail
task_archive=$(readlink -f "${1:?usage: deploy.sh fleet-release.tar.gz [--kb]}")
task_flags=" ${*:2} "
cd /var/www/fleet
bash scripts/release.sh
task_stage=$(mktemp -d /var/www/fleet/.stage-XXXXXX)
chmod 755 "$task_stage"  # rsync copies the stage dir mode onto /var/www/fleet
trap 'rm -rf -- "$task_stage"' EXIT
tar -xzf "$task_archive" -C "$task_stage"
test -f "$task_stage/dist/index.html"
test -f "$task_stage/app/api.py"
cp -an dist/assets/. "$task_stage/dist/assets/" 2>/dev/null || true
task_deps=same
cmp -s requirements.txt "$task_stage/requirements.txt" || task_deps=changed
rsync -a "$task_stage"/ /var/www/fleet/
chown fleet:fleet /var/www/fleet && chmod 755 /var/www/fleet
chown -R fleet:fleet app web dist public docs tests migrations scripts n8n infra
if [ "$task_deps" = changed ]; then .venv/bin/pip install -q -r requirements.txt; fi
.venv/bin/python -m compileall -q app
runuser -u fleet -- env FLEET_ENV=/etc/fleet.env .venv/bin/alembic upgrade head
# Workflow ids follow the host prefix; the definitions are imported into n8n separately.
N8N_PREFIX=$(sed -n 's/^N8N_PREFIX=//p' /etc/fleet-integrations.env) node n8n/build-workflows.mjs
if [[ "$task_flags" == *" --kb "* ]]; then
  runuser -u fleet -- env PYTHONPATH=. FLEET_ENV=/etc/fleet.env .venv/bin/python scripts/build_kb.py
fi
# Retrieval quality on reference questions (local embeddings, no paid calls) → reports/quality.json
mkdir -p reports && chown fleet:fleet reports
runuser -u fleet -- env PYTHONPATH=. FLEET_ENV=/etc/fleet.env .venv/bin/python -m app.quality || true
if [[ "$task_flags" == *" --quality "* ]]; then
  .venv/bin/pip install -q -r requirements-dev.txt
  runuser -u postgres -- psql -qc "DROP DATABASE IF EXISTS fleet_ci" -c "CREATE DATABASE fleet_ci OWNER fleet"
  runuser -u postgres -- psql -q -d fleet_ci -c "CREATE EXTENSION IF NOT EXISTS vector" -c "CREATE EXTENSION IF NOT EXISTS btree_gist"
  task_ci_url=$(sed -n "s/^DATABASE_URL=//p" /etc/fleet.env | sed "s#/fleet\$#/fleet_ci#")
  task_ci_env=(env DATABASE_URL="$task_ci_url" FLEET_ENV=/dev/null FLEET_INTEGRATIONS_ENV=/dev/null INTEGRATION_SECRET=ci FILE_ROOT=/tmp/fleet-ci-files PYTHONPATH=.)
  # A failed measurement must not stop the release: the stand restarts below either way.
  if runuser -u fleet -- "${task_ci_env[@]}" .venv/bin/alembic upgrade head >/dev/null \
    && runuser -u fleet -- "${task_ci_env[@]}" .venv/bin/python scripts/build_kb.py >/dev/null; then
    runuser -u fleet -- "${task_ci_env[@]}" .venv/bin/python tools/quality_report.py || true
  else
    echo "quality measurement failed" >&2
  fi
  runuser -u postgres -- psql -qc "DROP DATABASE IF EXISTS fleet_ci"
  rm -rf /tmp/fleet-ci-files
fi
pm2 startOrReload ecosystem.config.cjs --update-env
pm2 save --silent
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:3008/api/health; then printf '\nDeployed %s\n' "$(cat REVISION 2>/dev/null)"; exit 0; fi
  sleep 1
done
printf 'Health check failed; roll back with: cp -a "$(cat LAST_RELEASE)"/. /var/www/fleet/ && pm2 restart fleet-api fleet-worker\n' >&2
exit 1
