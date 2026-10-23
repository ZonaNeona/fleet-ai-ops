import time, json
from pathlib import Path
from sqlalchemy import text
from app.db import db, Space, now
from app.seed import create_space
from app.reports import report

with db() as s:
    sp = create_space(s, count=4000)
    sid = sp.id
try:
    with db() as s:
        for table in ["entries", "items", "bookings"]:
            s.execute(text("ANALYZE " + table))
    timings = []
    for i in range(3):
        with db() as s:
            sp = s.get(Space, sid)
            started = time.perf_counter()
            r = report(s, sp)
            timings.append(round((time.perf_counter() - started) * 1000, 1))
        print("4000 cars, ms:", timings[-1], flush=True)
    path = Path("reports/load.json")
    results = json.loads(path.read_text())
    results["scale"] = {
        "cars": 4000,
        "report_ms": max(timings),
        "samples_ms": timings,
        "prepared": "ANALYZE after fixture import",
        "tested_at": now().isoformat(),
        "revenue": r["revenue"],
    }
    results["targets_met"] = (
        results["normal"]["p95_ms"] < 700 and results["report"]["p95_ms"] < 2000 and max(timings) < 2000
    )
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results), flush=True)
finally:
    with db() as s:
        s.delete(s.get(Space, sid))
