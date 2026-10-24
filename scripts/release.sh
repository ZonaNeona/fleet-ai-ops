#!/usr/bin/env bash
# Snapshot before a release: backup + copy of the running code, path saved to LAST_RELEASE for rollback.
set -euo pipefail
cd /var/www/fleet
bash scripts/backup.sh
task_release=/var/www/fleet/releases/$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$task_release"
for task_path in app dist web public docs tests migrations scripts n8n b24app infra README.md requirements.txt requirements.lock package.json package-lock.json alembic.ini ecosystem.config.cjs; do
  # A path added in this very release is not on the host yet.
  if [ -e "$task_path" ]; then cp -a "$task_path" "$task_release/"; fi
done
printf '%s\n' "$task_release" > /var/www/fleet/LAST_RELEASE
chmod -R go-w "$task_release"
# Keep the ten latest snapshots.
ls -1d /var/www/fleet/releases/*/ | head -n -10 | xargs -r rm -rf --
printf '20 1 * * * root /bin/bash /var/www/fleet/scripts/backup.sh >> /var/log/fleet-backup.log 2>&1\n' > /etc/cron.d/fleet-backup
