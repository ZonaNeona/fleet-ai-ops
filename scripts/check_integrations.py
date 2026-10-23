import json, time
import httpx
from sqlalchemy import select, func
from app.db import db, Space, Item

out = []
sid = None
try:
    with httpx.Client(base_url="https://fleet.shvarev-demo.ru", timeout=40) as c:
        r = c.post("/api/v1/session", json={})
        r.raise_for_status()
        sid = c.get("/api/v1/session").json()["id"]
        for source in ["1c", "yandex-pro", "fines", "telematics", "1c"]:
            response = c.post("/api/v1/integrations/run", json={"source": source})
            response.raise_for_status()
            id = response.json()["id"]
            for _ in range(35):
                state = c.get("/api/v1/integrations").json()
                run = next(r for r in state["runs"] if r["id"] == id)
                if run["status"] in ("done", "failed") and run["data"].get("trace"):
                    break
                time.sleep(1)
            with db() as s:
                count = s.scalar(
                    select(func.count())
                    .select_from(Item)
                    .where(Item.space == sid, Item.kind == "source_record")
                )
            result = {
                "source": source,
                "status": run["status"],
                "execution": run["execution_id"],
                "rows": run["data"].get("rows"),
                "diffs": run["data"].get("diffs"),
                "nodes": [
                    {"name": t["node"], "status": t["status"], "ms": t["ms"]}
                    for t in run["data"].get("trace", [])
                ],
                "records_total": count,
                "error": run["data"].get("error"),
            }
            result["passed"] = run["status"] == "done" and len(result["nodes"]) >= 5
            out.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
        # Mock endpoints must not be exposed through the public site.
        assert c.post("/api/mock/1c/snapshot", json={}).status_code == 404
finally:
    if sid:
        with db() as s:
            sp = s.get(Space, sid)
            if sp:
                s.delete(sp)
    with open("reports/integrations.json", "w") as f:
        json.dump(
            {"checks": out, "passed": sum(x["passed"] for x in out)},
            f,
            ensure_ascii=False,
            indent=2,
        )
