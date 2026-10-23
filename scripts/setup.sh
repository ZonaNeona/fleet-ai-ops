#!/usr/bin/env bash
# First install on a fresh host (Ubuntu, PostgreSQL 16 with pgvector, Node 22, pm2, nginx).
# Code is unpacked to /var/www/fleet beforehand; afterwards use scripts/deploy.sh.
set -euo pipefail
cd /var/www/fleet
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends libpangoft2-1.0-0 fonts-dejavu-core
id fleet >/dev/null 2>&1 || useradd --system --home /var/lib/fleet --create-home --shell /usr/sbin/nologin fleet
install -d -o fleet -g fleet /var/lib/fleet/files /var/lib/fleet/backups
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python scripts/provision.py
.venv/bin/python scripts/setup_integrations.py
chown -R fleet:fleet /var/www/fleet
runuser -u fleet -- env FLEET_ENV=/etc/fleet.env .venv/bin/alembic upgrade head
runuser -u fleet -- env PYTHONPATH=. FLEET_ENV=/etc/fleet.env .venv/bin/python scripts/build_kb.py
cp infra/nginx.conf /etc/nginx/sites-available/fleet
printf 'Ready. Next: server_name in /etc/nginx/sites-available/fleet, certbot, pm2 start ecosystem.config.cjs\n'
