#!/usr/bin/env bash
# One-time on the host: the stand's own n8n instead of the old shared install.
#   cd /var/www/fleet && bash scripts/setup_n8n.sh
# Moves the n8n install from /var/www/lookin-n8n (a cancelled demo) to /var/www/fleet-n8n, starts it with a clean
# database holding only the stand's four workflows (prefix «fleet»), and renames the pm2 process to fleet-n8n.
# The old database is archived to /var/lib/fleet/backups first.
set -euo pipefail
OLD=/var/www/lookin-n8n
NEW=/var/www/fleet-n8n
STAND=/var/www/fleet
ENVF=/etc/fleet-integrations.env

setenv() { if grep -q "^$2=" "$1"; then sed -i "s|^$2=.*|$2=$3|" "$1"; else echo "$2=$3" >> "$1"; fi; }

if [ -d "$OLD" ] && [ ! -d "$NEW" ]; then
  install -d /var/lib/fleet/backups
  tar -czf "/var/lib/fleet/backups/lookin-n8n-$(date -u +%Y%m%dT%H%M%SZ).tgz" -C "$OLD" data workflows .env start.sh 2>/dev/null || true
  pm2 delete lookin-n8n >/dev/null 2>&1 || true
  mv "$OLD" "$NEW"
  rm -rf "$NEW/workflows" "$NEW/start-webhook.sh" "$NEW/data"   # LOOK.IN and EliteCar flows, the old database
  sed -i "s#$OLD#$NEW#g" "$NEW/.env" "$NEW/start.sh"
fi
install -d "$NEW/data"

# The stand's names: workflow ids «fleet-<source>», the scheduler header of the stand.
setenv "$ENVF" N8N_HOME "$NEW"
setenv "$ENVF" N8N_PREFIX fleet
setenv "$ENVF" N8N_SCHEDULER_HEADER X-Fleet-Scheduler
cd "$STAND"
.venv/bin/python scripts/setup_integrations.py
rm -f n8n/out/*.json
N8N_PREFIX=fleet node n8n/build-workflows.mjs

cd "$NEW"
set -a; . ./.env; set +a
./node_modules/.bin/n8n import:credentials --input=/var/lib/fleet/n8n-credentials.json
./node_modules/.bin/n8n import:workflow --separate --input="$STAND/n8n/out/"
./node_modules/.bin/n8n update:workflow --all --active=true

pm2 describe fleet-n8n >/dev/null 2>&1 || pm2 start "$NEW/start.sh" --name fleet-n8n --interpreter bash >/dev/null
pm2 restart fleet-n8n >/dev/null
pm2 restart fleet-api fleet-worker fleet-n8n-reader --update-env >/dev/null
pm2 save >/dev/null
echo "fleet-n8n ready: $(ls "$STAND"/n8n/out/*.json | wc -l) workflows"
