import json, subprocess, shutil, re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import httpx
from app.db import now

processes = json.loads(subprocess.check_output(["pm2", "jlist"]))
mine = [
    {
        "name": p["name"],
        "status": p["pm2_env"]["status"],
        "memory_mb": round(p["monit"]["memory"] / 1048576, 1),
        "restarts": p["pm2_env"]["restart_time"],
    }
    for p in processes
    if p["name"].startswith("fleet-")
]
hosts = set()
for p in Path("/etc/nginx/sites-enabled").glob("*"):
    if p.is_file():
        hosts.update(re.findall(r"\b([a-z0-9-]+\.shvarev-demo\.ru)\b", p.read_text()))


def check(host):
    try:
        r = httpx.get("https://" + host, timeout=10, follow_redirects=False)
        return {"host": host, "status": r.status_code}
    except Exception as e:
        return {"host": host, "error": type(e).__name__}


with ThreadPoolExecutor(max_workers=3) as pool:
    neighbors = list(pool.map(check, sorted(hosts)))
result = {
    "checked_at": now().isoformat(),
    "processes": mine,
    "combined_memory_mb": round(sum(x["memory_mb"] for x in mine), 1),
    "disk_free_gb": round(shutil.disk_usage("/var/www").free / 1073741824, 1),
    "health": httpx.get("https://fleet.shvarev-demo.ru/api/health").json(),
    "neighbors": neighbors,
}
Path("reports/runtime.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False))
