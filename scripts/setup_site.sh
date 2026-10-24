#!/usr/bin/env bash
# One-time on the host: the client site's server-rendered pages (/auto, /sitemap.xml, /robots.txt) go to the API.
#   bash scripts/setup_site.sh /etc/nginx/sites-available/fleet [more site files…]
set -euo pipefail
[ $# -ge 1 ] || { echo "usage: setup_site.sh <nginx site file>..." >&2; exit 2; }
for site in "$@"; do
  grep -q 'location ~ \^/(auto' "$site" && continue
  cp -a "$site" "$site.before-site"
  python3 - "$site" <<'PY'
import sys
path = sys.argv[1]
text = open(path).read()
block = r""" location ~ ^/(auto(/.*)?|sitemap\.xml|robots\.txt)$ {
   proxy_pass http://127.0.0.1:3008;
   proxy_set_header Host $host;
   proxy_set_header X-Forwarded-Proto $scheme;
   proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
 }
"""
anchor = " location / {"
assert anchor in text, "no location / in " + path
# certbot keeps one server block per port; the site goes into every block that serves the SPA
open(path, "w").write(text.replace(anchor, block + anchor))
PY
done
nginx -t
systemctl reload nginx
echo "site routes ready"
