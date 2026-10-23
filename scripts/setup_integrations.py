"""Run as root on the host; never writes credentials into the repository.

Creates the integration secret and the n8n header credentials the scheduled workflows use.
"""

import hashlib
import hmac
import json
import os
import secrets
import shutil
from pathlib import Path

from dotenv import dotenv_values

path = Path(os.getenv("FLEET_INTEGRATIONS_ENV", "/etc/fleet-integrations.env"))
if not path.exists():
    path.write_text("INTEGRATION_SECRET=" + secrets.token_hex(32) + "\n")
os.chmod(path, 0o640)
shutil.chown(path, user="root", group="fleet")
env = dotenv_values(path)
key = env["INTEGRATION_SECRET"]
prefix = env.get("N8N_PREFIX") or "fleet"
header = env.get("N8N_SCHEDULER_HEADER") or "X-Fleet-Scheduler"
creds = []
for source in ["1c", "yandex-pro", "fines", "telematics"]:
    value = hmac.new(
        key.encode(),
        json.dumps({"schedule": source}, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).hexdigest()
    creds.append(
        {
            "id": prefix + "-schedule-" + source,
            "name": "Парк · расписание " + source,
            "type": "httpHeaderAuth",
            "data": {"name": header, "value": value},
        }
    )
target = Path("/var/lib/fleet/n8n-credentials.json")
target.write_text(json.dumps(creds))
os.chmod(target, 0o600)
print("Integration secret and scheduler credentials prepared outside the repository")
