#!/usr/bin/env bash
# One-time on the host: Hermes Agent profile «fleet» next to the existing «pulse» one.
#   bash scripts/setup_hermes.sh
# The profile reaches the stand's tools through the stand's MCP server over HTTP with a server key; its API server
# listens on 127.0.0.1:8664. Keys are generated here and written only to the profile's .env and /etc/fleet.env.
set -euo pipefail
HERMES=/home/hermes/.local/bin/hermes
PROFILE=/home/hermes/.hermes/profiles/fleet
as_hermes() { sudo -u hermes HOME=/home/hermes HERMES_HOME=/home/hermes/.hermes "$@"; }
key() { openssl rand -hex 24; }
setenv() {  # setenv FILE NAME VALUE — replace or append, never print the value
  if grep -q "^$2=" "$1"; then sed -i "s|^$2=.*|$2=$3|" "$1"; else echo "$2=$3" >> "$1"; fi
}

[ -d "$PROFILE" ] || as_hermes "$HERMES" profile create fleet --clone-from pulse --no-alias >/dev/null
# The persona and skills are the fleet's, not the cloned ones.
rm -rf "$PROFILE"/skills/pulse-*
install -o hermes -g hermes -m 644 infra/hermes/SOUL.md "$PROFILE/SOUL.md"
for skill in infra/hermes/skills/*/; do
  install -d -o hermes -g hermes "$PROFILE/skills/$(basename "$skill")"
  install -o hermes -g hermes -m 644 "$skill/SKILL.md" "$PROFILE/skills/$(basename "$skill")/SKILL.md"
done
python3 - "$PROFILE/config.yaml" <<'PY'
import re, sys
path = sys.argv[1]
text = open(path).read()
block = """mcp_servers:
  fleet:
    url: http://127.0.0.1:3008/api/mcp
    headers:
      Authorization: Bearer ${FLEET_MCP_KEY}
    timeout: 60
"""
text = re.sub(r"mcp_servers:\n(?:[ \t]+.*\n)*", block, text)
open(path, "w").write(text)
PY

ENVF="$PROFILE/.env"
grep -q '^FLEET_MCP_KEY=' "$ENVF" || setenv "$ENVF" FLEET_MCP_KEY "$(key)"
if ! grep -q '^API_SERVER_PORT=8664$' "$ENVF"; then
  setenv "$ENVF" API_SERVER_PORT 8664
  setenv "$ENVF" API_SERVER_KEY "$(key)"
fi
chown hermes:hermes "$ENVF" && chmod 600 "$ENVF"
setenv /etc/fleet.env HERMES_API_URL http://127.0.0.1:8664
setenv /etc/fleet.env HERMES_API_KEY "$(sed -n 's/^API_SERVER_KEY=//p' "$ENVF")"
setenv /etc/fleet.env FLEET_HERMES_MCP_KEY "$(sed -n 's/^FLEET_MCP_KEY=//p' "$ENVF")"

install -m 644 infra/hermes/fleet-hermes.service /etc/systemd/system/fleet-hermes.service
systemctl daemon-reload
systemctl enable -q fleet-hermes
systemctl restart fleet-hermes
echo "fleet-hermes ready: restart the API and the worker to pick up /etc/fleet.env"
