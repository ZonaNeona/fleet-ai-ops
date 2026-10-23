#!/usr/bin/env bash
# Local release archive: tracked and new (not ignored) files plus fresh builds of the cabinet and the
# Bitrix24 app widget; the PHP app's tests run first.
#   bash scripts/pack.sh  ->  fleet-release.tar.gz
set -euo pipefail
cd "$(dirname "$0")/.."
npm run build
(cd b24app/widget && { [ -d node_modules ] || npm ci --no-audit --no-fund; } && npm run build)
php b24app/tests/run.php > /dev/null
git rev-parse --short HEAD > REVISION
{ git ls-files -co --exclude-standard; echo REVISION; find dist b24app/public/widget -type f; } | sort -u > .pack-list
tar -czf fleet-release.tar.gz -T .pack-list
rm .pack-list
printf 'fleet-release.tar.gz: %s files\n' "$(tar -tzf fleet-release.tar.gz | wc -l)"
