"""Real provider + local RAG checks. Synthetic test space; no Telegram messages."""

import json, time, resource
from types import SimpleNamespace
from sqlalchemy import select, func
from app.db import db, Space, Item, uid
from app.seed import create_space
from app.agent import run
from app.rag import answer

cases = [
    ("rag", "driver", "Какие документы нужны водителю?", "driver-documents"),
    ("agent", "driver", "Сколько я должен?", "get_balance"),
    (
        "agent",
        "driver",
        "Стучит подвеска. Подготовь заявку по моей машине.",
        "create_ticket",
    ),
    (
        "agent",
        "owner",
        "Какие 3 машины дают самый низкий результат и почему?",
        "vehicle_economics",
    ),
]
with db() as s:
    sp = create_space(s, count=24)
    sid = sp.id
results = []
try:
    for mode, role, q, expected in cases:
        start = time.monotonic()
        job = SimpleNamespace(
            id=uid(), space=sid, data={"mode": mode, "prompt": q, "role": role}
        )
        try:
            r = (answer if mode == "rag" else run)(job)
            passed = (
                any(expected in x.get("chunk_id", "") for x in r.get("sources", []))
                if mode == "rag"
                else any(
                    x["step"] == "tool"
                    and x["title"] == expected
                    and x.get("status") == "success"
                    for x in r["trace"]
                )
            )
            if expected == "create_ticket":
                passed = passed and bool(r.get("drafts"))
            results.append(
                {
                    "mode": mode,
                    "role": role,
                    "query": q,
                    "passed": passed,
                    "elapsed_ms": round((time.monotonic() - start) * 1000),
                    "result": r,
                }
            )
        except Exception as e:
            results.append(
                {
                    "mode": mode,
                    "role": role,
                    "query": q,
                    "passed": False,
                    "error": type(e).__name__ + ": " + str(e)[:180],
                }
            )
        print(
            json.dumps(
                {k: v for k, v in results[-1].items() if k != "result"},
                ensure_ascii=False,
            ),
            flush=True,
        )
finally:
    with db() as s:
        sp = s.get(Space, sid)
        if sp:
            s.delete(sp)
    out = {
        "checks": results,
        "passed": sum(r["passed"] for r in results),
        "total": len(results),
        "rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
    }
    with open("reports/under-live.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in out.items() if k != "checks"}))
