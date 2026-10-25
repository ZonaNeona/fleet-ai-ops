#!/usr/bin/env bash
# One-time on the host: Hermes Agent profile «fleet» for the agent router (ADR 0014).
#   bash scripts/setup_hermes.sh            (Hermes Agent installed for the user «hermes»)
# The profile's API server listens on 127.0.0.1:8664; its tools come from the stand's MCP server over HTTP with a
# server key. Keys are generated here and written only to the profile's .env and /etc/fleet.env.
set -euo pipefail
HERMES=/home/hermes/.local/bin/hermes
PROFILE=/home/hermes/.hermes/profiles/fleet
as_hermes() { sudo -u hermes HOME=/home/hermes HERMES_HOME=/home/hermes/.hermes "$@"; }
key() { openssl rand -hex 24; }
setenv() {  # setenv FILE NAME VALUE — replace or append, never print the value
  if grep -q "^$2=" "$1"; then sed -i "s|^$2=.*|$2=$3|" "$1"; else echo "$2=$3" >> "$1"; fi
}
fleet() { sed -n "s/^$1=//p" /etc/fleet.env; }

[ -d "$PROFILE" ] || as_hermes "$HERMES" profile create fleet --no-alias >/dev/null
install -o hermes -g hermes -m 644 infra/hermes/SOUL.md "$PROFILE/SOUL.md"
for skill in infra/hermes/skills/*/; do
  install -d -o hermes -g hermes "$PROFILE/skills/$(basename "$skill")"
  install -o hermes -g hermes -m 644 "$skill/SKILL.md" "$PROFILE/skills/$(basename "$skill")/SKILL.md"
done
sed "s|__OPENROUTER_BASE_URL__|$(fleet OPENROUTER_BASE_URL)|" infra/hermes/config.yaml > "$PROFILE/config.yaml"
chown hermes:hermes "$PROFILE/config.yaml"

ENVF="$PROFILE/.env"
touch "$ENVF"
setenv "$ENVF" OPENROUTER_API_KEY "$(fleet OPENROUTER_API_KEY)"
setenv "$ENVF" OPENROUTER_BASE_URL "$(fleet OPENROUTER_BASE_URL)"
setenv "$ENVF" API_SERVER_PORT 8664
grep -q '^API_SERVER_KEY=.' "$ENVF" || setenv "$ENVF" API_SERVER_KEY "$(key)"
grep -q '^FLEET_MCP_KEY=.' "$ENVF" || setenv "$ENVF" FLEET_MCP_KEY "$(key)"
chown hermes:hermes "$ENVF" && chmod 600 "$ENVF"
setenv /etc/fleet.env HERMES_API_URL http://127.0.0.1:8664
setenv /etc/fleet.env HERMES_API_KEY "$(sed -n 's/^API_SERVER_KEY=//p' "$ENVF")"
setenv /etc/fleet.env FLEET_HERMES_MCP_KEY "$(sed -n 's/^FLEET_MCP_KEY=//p' "$ENVF")"

install -m 644 infra/hermes/fleet-hermes.service /etc/systemd/system/fleet-hermes.service
systemctl daemon-reload
systemctl enable -q fleet-hermes
systemctl restart fleet-hermes
echo "fleet-hermes ready: restart the API and the worker to pick up /etc/fleet.env"
