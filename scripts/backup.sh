#!/usr/bin/env bash
# Nightly and pre-release backup: database dump + uploaded documents, kept for 7 days.
set -euo pipefail
umask 077
task_stamp=$(date -u +%Y%m%dT%H%M%SZ)
task_backup=/var/lib/fleet/backups/$task_stamp
mkdir -p "$task_backup"
runuser -u postgres -- pg_dump --format=custom fleet > "$task_backup/database.dump"
tar -czf "$task_backup/documents.tar.gz" -C /var/lib/fleet files
sha256sum "$task_backup/database.dump" "$task_backup/documents.tar.gz" > "$task_backup/SHA256SUMS"
find /var/lib/fleet/backups -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf -- {} +
printf '%s\n' "$task_backup"
