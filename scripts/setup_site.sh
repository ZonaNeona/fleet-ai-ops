#!/usr/bin/env bash
# One-time on the host: the client site's server-rendered pages (/auto, /sitemap.xml, /robots.txt) go to the API.
#   bash scripts/setup_site.sh /etc/nginx/sites-available/fleet [more site files…]
set -euo pipefail
[ $# -ge 1 ] || { echo "usage: setup_site.sh <nginx site file>..." >&2; exit 2; }
for site in "$@"; do
  if grep -q 'location ~ \^/(auto' "$site"; then
    # an earlier release routed only the site: add the training portal to the same location
    grep -q 'gov(/' "$site" || sed -i 's#location ~ ^/(auto(/\.\*)?|sitemap#location ~ ^/(auto(/.*)?|gov(/.*)?|sitemap#' "$site"
    continue
  fi
  cp -a "$site" "$site.before-site"
  python3 - "$site" <<'PY'
import sys
path = sys.argv[1]
text = open(path).read()
block = r""" location ~ ^/(auto(/.*)?|gov(/.*)?|sitemap\.xml|robots\.txt)$ {
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
# Cache headers: an old page shell must never point a returning visitor at bundles a release removed.
for site in "$@"; do
  grep -q 'location = /index.html' "$site" && continue
  python3 - "$site" <<'PY'
import sys
path = sys.argv[1]
text = open(path).read()
block = r""" location = /index.html {
   add_header Cache-Control "no-cache";
   add_header X-Content-Type-Options nosniff;
   add_header Referrer-Policy same-origin;
 }
 location /assets/ {
   add_header Cache-Control "public, max-age=31536000, immutable";
   add_header X-Content-Type-Options nosniff;
 }
"""
open(path, "w").write(text.replace(" location / {", block + " location / {"))
PY
done
nginx -t
systemctl reload nginx
echo "site routes ready"
