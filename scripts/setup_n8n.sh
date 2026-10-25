#!/usr/bin/env bash
# One-time on the host: the stand's own n8n with its four workflows.
#   cd /var/www/fleet && bash scripts/setup_n8n.sh
# Installs n8n into /var/www/fleet-n8n (localhost:5678, data next to it), imports the scheduler credentials and the
# workflows built by n8n/build-workflows.mjs with the stand's prefix, activates them and runs n8n under pm2.
# Safe to run again: credentials and workflows are re-imported by id.
set -euo pipefail
N8N=/var/www/fleet-n8n
STAND=/var/www/fleet
ENVF=/etc/fleet-integrations.env
VERSION=${N8N_VERSION:-1.120.4}

setenv() { if grep -q "^$2=" "$1"; then sed -i "s|^$2=.*|$2=$3|" "$1"; else echo "$2=$3" >> "$1"; fi; }

if [ ! -x "$N8N/node_modules/.bin/n8n" ]; then
  install -d "$N8N/data"
  (cd "$N8N" && npm init -y >/dev/null && npm install --no-audit --no-fund "n8n@$VERSION" >/dev/null)
fi
if [ ! -f "$N8N/.env" ]; then
  cat > "$N8N/.env" <<ENV
N8N_ENCRYPTION_KEY=$(openssl rand -hex 24)
N8N_USER_FOLDER=$N8N/data
N8N_HOST=127.0.0.1
N8N_LISTEN_ADDRESS=127.0.0.1
N8N_PORT=5678
N8N_PROTOCOL=http
N8N_SECURE_COOKIE=false
N8N_DIAGNOSTICS_ENABLED=false
N8N_VERSION_NOTIFICATIONS_ENABLED=false
N8N_TEMPLATES_ENABLED=false
N8N_PERSONALIZATION_ENABLED=false
N8N_HIRING_BANNER_ENABLED=false
N8N_METRICS=false
EXECUTIONS_DATA_SAVE_ON_ERROR=all
EXECUTIONS_DATA_SAVE_ON_SUCCESS=all
EXECUTIONS_DATA_PRUNE=true
EXECUTIONS_DATA_MAX_AGE=168
GENERIC_TIMEZONE=Europe/Moscow
TZ=Europe/Moscow
N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=true
N8N_ENDPOINT_WEBHOOK=webhook
N8N_ENDPOINT_WEBHOOK_TEST=webhook-test
NODE_FUNCTION_ALLOW_BUILTIN=crypto
ENV
  chmod 600 "$N8N/.env"
fi
cat > "$N8N/start.sh" <<'START'
#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
set -a; . ./.env; set +a
exec ./node_modules/.bin/n8n start
START
chmod 755 "$N8N/start.sh"

# Workflow ids «fleet-<source>», the stand's scheduler header and credentials.
setenv "$ENVF" N8N_HOME "$N8N"
setenv "$ENVF" N8N_PREFIX fleet
setenv "$ENVF" N8N_SCHEDULER_HEADER X-Fleet-Scheduler
cd "$STAND"
.venv/bin/python scripts/setup_integrations.py
rm -f n8n/out/*.json
N8N_PREFIX=fleet node n8n/build-workflows.mjs

cd "$N8N"
set -a; . ./.env; set +a
./node_modules/.bin/n8n import:credentials --input=/var/lib/fleet/n8n-credentials.json
./node_modules/.bin/n8n import:workflow --separate --input="$STAND/n8n/out/"
./node_modules/.bin/n8n update:workflow --all --active=true

pm2 describe fleet-n8n >/dev/null 2>&1 || pm2 start "$N8N/start.sh" --name fleet-n8n --interpreter bash >/dev/null
pm2 restart fleet-n8n >/dev/null
pm2 restart fleet-api fleet-worker fleet-n8n-reader --update-env >/dev/null
pm2 save >/dev/null
echo "fleet-n8n ready: $(ls "$STAND"/n8n/out/*.json | wc -l) workflows"
