"""Exercise the real n8n error branch without touching another visitor's data."""

import json
import time
from pathlib import Path

import httpx
from sqlalchemy import select, func, delete
from app.db import db, Space, Item, Job
from app.seed import create_space
from app.integrations import N8N_PREFIX, enqueue, read_execution

sid = None
try:
    with db() as s:
        sp = create_space(s, count=4)
        sid = sp.id
        ctx = enqueue(s, sp, "1c", schedule=True)
        s.flush()
        # This script drives the real webhook directly, so do not let the worker race it.
        s.execute(delete(Job).where(Job.space == sid, Job.kind == "integration_trace"))
    ctx["signature"] = "0" * 64
    response = httpx.post(
        f"http://127.0.0.1:5678/webhook/{N8N_PREFIX}-1c", json=ctx, timeout=30
    )
    for _ in range(12):
        execution = read_execution(ctx["run"])
        if execution.get("finished"):
            break
        time.sleep(0.5)
    trace = execution.get("trace", [])
    assert any(
        step.get("status") == "error" for step in trace
    ), "No real error node recorded"
    assert any(
        "Ошибка" in step.get("node", "") for step in trace
    ), "Error branch did not execute"
    with db() as s:
        records = s.scalar(
            select(func.count())
            .select_from(Item)
            .where(Item.space == sid, Item.kind == "source_record")
        )
    assert records == 0, "Rejected packet changed data"
    result = {
        "passed": True,
        "execution": execution["id"],
        "http_status": response.status_code,
        "trace": trace,
        "records_written": records,
    }
    Path("reports/integration-failure.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2)
    )
    print(
        json.dumps(
            {"passed": True, "execution": execution["id"], "records_written": records}
        )
    )
finally:
    if sid:
        with db() as s:
            sp = s.get(Space, sid)
            if sp:
                s.delete(sp)
