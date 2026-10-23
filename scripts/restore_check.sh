#!/usr/bin/env bash
# Proves the backup restores: fresh dump into a scratch database, counts must match the live one.
set -euo pipefail
task_backup=$(bash /var/www/fleet/scripts/backup.sh)
task_db=fleet_restore_$(date +%s)
task_docs=/var/lib/fleet/restore-check-$(date +%s)
runuser -u postgres -- createdb "$task_db"
mkdir -p "$task_docs"
trap 'runuser -u postgres -- dropdb "$task_db"; rm -rf -- "$task_docs"' EXIT
runuser -u postgres -- pg_restore --no-owner --dbname="$task_db" < "$task_backup/database.dump"
tar -xzf "$task_backup/documents.tar.gz" -C "$task_docs"
task_live=$(runuser -u postgres -- psql -At -d fleet -c 'SELECT count(*) FROM entries')
task_restored=$(runuser -u postgres -- psql -At -d "$task_db" -c 'SELECT count(*) FROM entries')
test "$task_live" = "$task_restored"
task_vectors=$(runuser -u postgres -- psql -At -d fleet -c 'SELECT count(*) FROM kb_chunk WHERE vector_dims(embedding)=384')
task_restored_vectors=$(runuser -u postgres -- psql -At -d "$task_db" -c 'SELECT count(*) FROM kb_chunk WHERE vector_dims(embedding)=384')
test "$task_vectors" = "$task_restored_vectors"
diff -qr /var/lib/fleet/files "$task_docs/files"
mkdir -p /var/www/fleet/reports
printf '{"database_entries":%s,"restore_entries":%s,"knowledge_vectors":%s,"restored_vectors":%s,"documents":"identical","verified_at":"%s"}\n' "$task_live" "$task_restored" "$task_vectors" "$task_restored_vectors" "$(date -u +%FT%TZ)" > /var/www/fleet/reports/restore.json
cat /var/www/fleet/reports/restore.json
