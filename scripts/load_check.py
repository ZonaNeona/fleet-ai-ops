import asyncio, hashlib, secrets, time, json, math
from pathlib import Path
import httpx
from app.db import db, Space, Item, now
from sqlalchemy import select
from app.seed import create_space
from app.reports import report


def stats(rows):
    times = sorted(x["ms"] for x in rows)
    return {
        "requests": len(rows),
        "errors": sum(x["status"] != 200 for x in rows),
        "p50_ms": times[len(times) // 2],
        "p95_ms": times[math.ceil(len(times) * 0.95) - 1],
        "max_ms": max(times),
    }


async def main():
    created = []
    sessions = []
    cards = []
    Path("reports").mkdir(exist_ok=True)
    try:
        for i in range(20):
            with db() as s:
                sp = create_space(s)
                token = secrets.token_urlsafe(32)
                sp.token = hashlib.sha256(token.encode()).hexdigest()
                created.append(sp.id)
                sessions.append(token)
                cards.append(
                    s.scalar(select(Item.id).where(Item.space == sp.id, Item.kind == "vehicle").limit(1))
                )
            print("Prepared visitor", i + 1, flush=True)
        async with httpx.AsyncClient(
            base_url="https://fleet.shvarev-demo.ru", timeout=40, limits=httpx.Limits(max_connections=20)
        ) as client:

            async def one(token, path):
                started = time.perf_counter()
                r = await client.get(path, headers={"Cookie": "fleet_session=" + token})
                return {"ms": round((time.perf_counter() - started) * 1000, 1), "status": r.status_code}

            normal = []
            reports = []
            bootstrap = await asyncio.gather(*(one(t, "/api/v1/bootstrap") for t in sessions))
            for _ in range(3):
                normal += await asyncio.gather(
                    *(one(t, "/api/v1/items/" + c) for t, c in zip(sessions, cards))
                )
                reports += await asyncio.gather(*(one(t, "/api/v1/report") for t in sessions))
        results = {
            "tested_at": now().isoformat(),
            "concurrency": 20,
            "normal_endpoint": "vehicle detail with ledger",
            "normal": stats(normal),
            "initial_bootstrap": stats(bootstrap),
            "report": stats(reports),
        }
        print(json.dumps(results), flush=True)
        with db() as s:
            print("Preparing 4000-car dataset", flush=True)
            large = create_space(s, count=4000)
            created.append(large.id)
        with db() as s:
            large = s.get(Space, large.id)
            started = time.perf_counter()
            r = report(s, large)
            elapsed = (time.perf_counter() - started) * 1000
            results["scale"] = {"cars": r["fleet"], "report_ms": round(elapsed, 1), "revenue": r["revenue"]}
        results["targets_met"] = (
            results["normal"]["errors"] == 0
            and results["report"]["errors"] == 0
            and results["normal"]["p95_ms"] < 700
            and results["report"]["p95_ms"] < 2000
            and results["scale"]["report_ms"] < 2000
        )
        Path("reports/load.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(json.dumps(results), flush=True)
    finally:
        with db() as s:
            for sid in created:
                sp = s.get(Space, sid)
                if sp:
                    s.delete(sp)


asyncio.run(main())
