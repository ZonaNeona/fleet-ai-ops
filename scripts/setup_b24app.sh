#!/usr/bin/env bash
# One-time on the host: PHP-FPM for the Bitrix24 app (b24app/) and its two nginx locations.
#   bash scripts/setup_b24app.sh /etc/nginx/sites-available/fleet [more site files…]
# A dedicated on-demand pool under the stand's user: no PHP process stays in memory while nobody calls the app.
set -euo pipefail
[ $# -ge 1 ] || { echo "usage: setup_b24app.sh <nginx site file>..." >&2; exit 2; }
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends php8.3-fpm php8.3-cli >/dev/null
install -d -o fleet -g fleet /var/lib/fleet/b24app
cat > /etc/php/8.3/fpm/pool.d/fleet-b24app.conf <<'POOL'
[fleet-b24app]
user = fleet
group = fleet
listen = /run/php/fleet-b24app.sock
listen.owner = www-data
listen.group = www-data
pm = ondemand
pm.max_children = 3
pm.process_idle_timeout = 30s
env[FLEET_API] = http://127.0.0.1:3008
env[B24APP_VAR] = /var/lib/fleet/b24app
php_admin_value[memory_limit] = 64M
POOL
# The distribution's default pool is not used by anything on this host.
[ -f /etc/php/8.3/fpm/pool.d/www.conf ] && mv /etc/php/8.3/fpm/pool.d/www.conf /etc/php/8.3/fpm/pool.d/www.conf.disabled
systemctl enable --now php8.3-fpm >/dev/null
systemctl restart php8.3-fpm
for site in "$@"; do
  grep -q 'location /b24app/' "$site" && continue
  cp -a "$site" "$site.before-b24app"
  python3 - "$site" <<'PY'
import sys
path = sys.argv[1]
text = open(path).read()
block = r""" location ~ ^/b24app/(.+\.php)$ {
   include fastcgi_params;
   fastcgi_param SCRIPT_FILENAME /var/www/fleet/b24app/public/$1;
   fastcgi_pass unix:/run/php/fleet-b24app.sock;
 }
 location /b24app/ { alias /var/www/fleet/b24app/public/; }
"""
anchor = " location / {"
assert anchor in text, "no location / in " + path
open(path, "w").write(text.replace(anchor, block + anchor, 1))
PY
done
nginx -t
systemctl reload nginx
grep -q '^B24_EMULATOR_URL=' /etc/fleet.env || echo 'B24_EMULATOR_URL=http://127.0.0.1:3008' >> /etc/fleet.env
echo "b24app ready"
