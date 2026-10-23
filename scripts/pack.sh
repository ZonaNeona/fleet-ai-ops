#!/usr/bin/env bash
# Local release archive: tracked and new (not ignored) files plus a fresh frontend build.
#   bash scripts/pack.sh  ->  fleet-release.tar.gz
set -euo pipefail
cd "$(dirname "$0")/.."
npm run build
git rev-parse --short HEAD > REVISION
{ git ls-files -co --exclude-standard; echo REVISION; find dist -type f; } | sort -u > .pack-list
tar -czf fleet-release.tar.gz -T .pack-list
rm .pack-list
printf 'fleet-release.tar.gz: %s files\n' "$(tar -tzf fleet-release.tar.gz | wc -l)"
