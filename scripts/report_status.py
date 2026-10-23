import json
from pathlib import Path
from app.db import db, Usage, Space, now
from sqlalchemy import select, func, text

for path in ["reports/ai-evaluation.json", "reports/load.json", "reports/restore.json"]:
    p = Path(path)
    if p.exists():
        d = json.loads(p.read_text())
        if isinstance(d, list):
            d = [
                {
                    "summary": r["summary"],
                    "failures": [
                        {
                            "case": c["case"],
                            "kind": c["kind"],
                            "prompt": c.get("prompt"),
                            "result": c.get("result"),
                            "error": c.get("error"),
                        }
                        for c in r["cases"]
                        if not c["passed"]
                    ],
                }
                for r in d
            ]
        print(path, json.dumps(d, ensure_ascii=False))
with db() as s:
    print(
        "usage",
        str(s.scalar(select(func.sum(Usage.cost)))),
        "spaces",
        s.scalar(select(func.count()).select_from(Space)),
    )
with db() as s:
    print(
        "database_activity",
        [
            dict(r)
            for r in s.execute(
                text(
                    "SELECT pid,state,wait_event_type,wait_event,left(query,55) AS operation FROM pg_stat_activity WHERE datname=current_database() AND state != 'idle'"
                )
            ).mappings()
        ],
    )
