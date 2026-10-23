"""Signed synthetic sources; real n8n execution and transactional reconciliation."""

import os, json, hmac, hashlib, time
from decimal import Decimal
from datetime import timedelta
from types import SimpleNamespace
import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import text, select, func
from .db import db, Space, Item, Entry, Job, now, uid
from .domain import fail, audit
from .seed import add

load_dotenv(os.getenv("FLEET_INTEGRATIONS_ENV", "/etc/fleet-integrations.env"))
# Workflow ids in n8n and the scheduler header name; a host may keep its earlier values.
N8N_PREFIX = os.getenv("N8N_PREFIX", "fleet")
SCHEDULER_HEADER = os.getenv("N8N_SCHEDULER_HEADER", "X-Fleet-Scheduler")
router = APIRouter()
SOURCES = {
    "1c": "1С · OData",
    "yandex-pro": "Яндекс Про",
    "fines": "Штрафы ГИБДД",
    "telematics": "Телематика",
}
ALLOWED = {"owner", "admin", "finance", "manager"}
FIELDS = {
    "mileage": "Пробег, км",
    "charges": "Начисления, ₽",
    "payments": "Поступления, ₽",
    "fine": "Постановление, ₽",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign(value):
    key = os.getenv("INTEGRATION_SECRET")
    if not key:
        raise RuntimeError("Интеграции не настроены")
    return hmac.new(key.encode(), canonical(value).encode(), hashlib.sha256).hexdigest()


def verify_context(ctx):
    required = {"run", "space", "source", "expires", "signature"}
    if set(ctx) != required:
        fail("Некорректный контекст", 403)
    if (
        ctx["source"] not in SOURCES
        or not isinstance(ctx["expires"], int)
        or not time.time() < ctx["expires"] < time.time() + 700
    ):
        fail("Контекст истёк", 403)
    body = {k: v for k, v in ctx.items() if k != "signature"}
    if not hmac.compare_digest(str(ctx["signature"]), sign(body)):
        fail("Некорректная подпись", 403)
    return body


def get_sync(s, id):
    return (
        s.execute(text("SELECT * FROM source_sync WHERE id=:id"), {"id": id})
        .mappings()
        .first()
    )


def save_sync(s, id, **fields):
    allowed = {"data", "status", "finished", "execution_id"}
    if not set(fields) <= allowed:
        raise ValueError("Invalid sync fields")
    params = {"id": id, **fields}
    sets = []
    for k, v in fields.items():
        sets.append(k + "=" + ("CAST(:data AS jsonb)" if k == "data" else ":" + k))
        if k == "data":
            params[k] = json.dumps(v, ensure_ascii=False)
    s.execute(
        text("UPDATE source_sync SET " + ",".join(sets) + " WHERE id=:id"), params
    )


def enqueue(s, sp, source, schedule=False):
    run = uid()
    ctx = {
        "run": run,
        "space": sp.id,
        "source": source,
        "expires": int(time.time()) + 600,
    }
    ctx["signature"] = sign(ctx)
    s.execute(
        text(
            "INSERT INTO source_sync(id,space,source,status,data) VALUES(:id,:space,:source,'queued',CAST(:data AS jsonb))"
        ),
        {
            "id": run,
            "space": sp.id,
            "source": source,
            "data": json.dumps(
                {"mode": "synthetic", "trigger": "schedule" if schedule else "manual"}
            ),
        },
    )
    s.add(
        Job(
            space=sp.id,
            kind="integration_trace" if schedule else "integration",
            due=now() + timedelta(seconds=35) if schedule else now(),
            data={"role": sp.role, "context": ctx},
            result={},
        )
    )
    return ctx


class RunInput(BaseModel):
    source: str


@router.post("/api/v1/integrations/run")
def launch(body: RunInput, request: Request):
    from .api import auth

    with db() as s:
        sp = auth(s, request)
        if sp.role not in ALLOWED:
            fail("Запуск доступен сотрудникам и собственнику", 403)
        if body.source not in SOURCES:
            fail("Неизвестный источник")
        recent = s.execute(
            text(
                "SELECT count(*) FROM source_sync WHERE space=:space AND started>now()-interval '1 minute'"
            ),
            {"space": sp.id},
        ).scalar()
        if recent >= 8:
            fail("Лимит 8 запусков в минуту", 429)
        ctx = enqueue(s, sp, body.source)
        sp.data = {
            **sp.data,
            "integration_sources": sorted(
                set(sp.data.get("integration_sources", [])) | {body.source}
            ),
        }
        return {"id": ctx["run"], "state": "queued"}


def local_only(request):
    if request.client.host not in ("127.0.0.1", "::1"):
        fail("Внутренний источник", 404)


@router.get("/api/mock/schedule/{source}")
def schedule(source: str, request: Request):
    local_only(request)
    if source not in SOURCES or not hmac.compare_digest(
        request.headers.get(SCHEDULER_HEADER, ""), sign({"schedule": source})
    ):
        fail("Недостаточно прав", 403)
    with db() as s:
        s.execute(text("SELECT pg_advisory_xact_lock(814633)"))
        runs = []
        for sp in s.scalars(
            select(Space)
            .where(Space.touched > now() - timedelta(hours=24))
            .order_by(Space.touched.desc())
            .limit(100)
        ):
            if source not in sp.data.get("integration_sources", []):
                continue
            fresh = s.execute(
                text(
                    "SELECT id FROM source_sync WHERE space=:sp AND source=:source AND started>now()-interval '1 hour' LIMIT 1"
                ),
                {"sp": sp.id, "source": source},
            ).first()
            if not fresh:
                runs.append(enqueue(s, sp, source, True))
            if len(runs) >= 5:
                break
        return {"runs": runs}


def snapshot(s, sp):
    money = {}
    for vehicle, kind, total in s.execute(
        select(Entry.vehicle, Entry.kind, func.sum(Entry.amount))
        .where(Entry.space == sp.id, Entry.kind.in_(["charge", "payment"]))
        .group_by(Entry.vehicle, Entry.kind)
    ):
        money.setdefault(vehicle, {})["charges" if kind == "charge" else "payments"] = (
            str(total)
        )
    return [
        {
            "vehicle_code": v.code,
            "vehicle": v.id,
            "model": v.data["model"],
            "direction": v.data["direction"],
            "mileage": str(v.data["mileage"]),
            "charges": money.get(v.id, {}).get("charges", "0.00"),
            "payments": money.get(v.id, {}).get("payments", "0.00"),
        }
        for v in s.scalars(
            select(Item)
            .where(Item.space == sp.id, Item.kind == "vehicle")
            .order_by(Item.code)
        )
    ]


@router.post("/api/mock/{source}/snapshot")
async def mock(source: str, request: Request):
    local_only(request)
    ctx = await request.json()
    body = verify_context(ctx)
    if source != body["source"]:
        fail("Источник не совпадает", 403)
    with db() as s:
        sync = get_sync(s, ctx["run"])
        sp = s.get(Space, ctx["space"])
        if not sync or not sp or sync["space"] != sp.id or sync["source"] != source:
            fail("Запуск не найден", 404)
        rows = snapshot(s, sp)
        normal = []
        raw = []
        for i, r in enumerate(rows):
            if source == "1c":
                item = {
                    "vehicle_code": r["vehicle_code"],
                    "mileage": str(int(r["mileage"]) + (120 if i in (2, 8) else 0)),
                    "charges": str(
                        Decimal(r["charges"]) + (Decimal(2300) if i == 12 else 0)
                    ),
                }
                raw.append(
                    {
                        "Ref_Key": item["vehicle_code"],
                        "Description": r["model"],
                        "Distance": item["mileage"],
                        "AccruedAmount": item["charges"],
                    }
                )
            elif source == "yandex-pro":
                if r["direction"] != "taxi":
                    continue
                item = {
                    "vehicle_code": r["vehicle_code"],
                    "payments": str(
                        Decimal(r["payments"]) + (Decimal(900) if i == 4 else 0)
                    ),
                }
                raw.append({"car_id": item["vehicle_code"], "income": item["payments"]})
            elif source == "telematics":
                item = {
                    "vehicle_code": r["vehicle_code"],
                    "mileage": str(int(r["mileage"]) + (175 if i in (5, 18) else 0)),
                }
                raw.append(
                    {"vehicle": item["vehicle_code"], "odometer": item["mileage"]}
                )
            else:
                if i not in (1, 3, 10, 25):  # 1 — машина демо-водителя: штраф виден в боте
                    continue
                item = {
                    "vehicle_code": r["vehicle_code"],
                    "fine": "500.00",
                    "external_id": "DEMO-FINE-" + r["vehicle_code"],
                }
                raw.append(
                    {
                        "registration": item["vehicle_code"],
                        "amount": item["fine"],
                        "resolution": item["external_id"],
                    }
                )
            normal.append(item)
        payload = {"context": ctx, "rows": normal}
        return {
            "value": raw,
            "@odata.context": (
                "$metadata#Catalog_ТС+AccumulationRegister_Начисления"
                if source == "1c"
                else None
            ),
            "context": ctx,
            "signature": sign(payload),
            "mode": "synthetic",
        }


class Ingest(BaseModel):
    context: dict
    rows: list[dict] = Field(max_length=5000)
    signature: str
    execution_id: str = Field(max_length=80)


@router.post("/api/v1/integrations/ingest")
def ingest(body: Ingest):
    ctx = body.context
    verify_context(ctx)
    if not hmac.compare_digest(
        body.signature, sign({"context": ctx, "rows": body.rows})
    ):
        fail("Пакет изменён: подпись не совпадает", 403)
    with db() as s:
        s.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:sp))"), {"sp": ctx["space"]}
        )
        sync = get_sync(s, ctx["run"])
        if not sync or sync["space"] != ctx["space"] or sync["source"] != ctx["source"]:
            fail("Запуск не найден", 404)
        if sync["data"].get("ingested"):
            return {
                "id": ctx["run"],
                "status": "done",
                "duplicate": True,
                "rows": sync["data"]["rows"],
                "diffs": sync["data"]["diffs"],
                "execution_id": body.execution_id,
            }
        sp = s.get(Space, ctx["space"])
        local = {r["vehicle_code"]: r for r in snapshot(s, sp)}
        diffs = 0
        for row in body.rows:
            current = local.get(row.get("vehicle_code"))
            if not current:
                fail("Неизвестный автомобиль в пакете")
            code = ctx["source"] + ":" + row["vehicle_code"]
            record = s.scalar(
                select(Item).where(
                    Item.space == sp.id, Item.kind == "source_record", Item.code == code
                )
            )
            data = {
                "source": ctx["source"],
                "vehicle": current["vehicle"],
                "values": row,
                "run": ctx["run"],
                "at": now().isoformat(),
            }
            if ctx["source"] == "fines":
                previous = record.data.get("values", {}) if record else {}
                # Demo policy is stable across syncs; it is not a statement of traffic law.
                data["values"] = {**row, "discount_percent": 50,
                    "discount_until": previous.get("discount_until") or (now() + timedelta(days=10)).date().isoformat(),
                    "discount_rule": "Учебное условие: скидка 50% в течение 10 дней"}
            if record:
                record.data = data
                record.version += 1
            else:
                record = add(s, sp.id, "source_record", code, data)
                if ctx["source"] == "fines":
                    audit(s, sp, "Новое учебное постановление · " + row.get("external_id", code), record.id)
            for field in FIELDS:
                if field not in row:
                    continue
                different = Decimal(str(row[field])) != Decimal(current.get(field, "0"))
                dcode = code + ":" + field
                old = s.scalar(
                    select(Item).where(
                        Item.space == sp.id,
                        Item.kind == "discrepancy",
                        Item.code == dcode,
                    )
                )
                values = {
                    "source": ctx["source"],
                    "vehicle": current["vehicle"],
                    "vehicle_code": row["vehicle_code"],
                    "field": field,
                    "field_label": FIELDS[field],
                    "local": current.get(field, "0.00"),
                    "external": row[field],
                    "status": "open" if different else "resolved",
                    "run": ctx["run"],
                }
                if old:
                    old.data = values
                    old.version += 1
                elif different:
                    add(s, sp.id, "discrepancy", dcode, values)
                diffs += int(different)
        save_sync(
            s,
            ctx["run"],
            status="done",
            finished=now(),
            execution_id=body.execution_id,
            data={
                **sync["data"],
                "rows": len(body.rows),
                "diffs": diffs,
                "ingested": True,
            },
        )
        audit(
            s,
            SimpleNamespace(id=sp.id, role="admin", data=sp.data),
            "Сверка " + SOURCES[ctx["source"]] + ": " + str(diffs) + " расхождений",
            None,
            source=ctx["source"],
        )
        return {
            "id": ctx["run"],
            "status": "done",
            "rows": len(body.rows),
            "diffs": diffs,
            "execution_id": body.execution_id,
        }


def read_execution(run):
    stamp = str(int(time.time()))
    path = "/execution/" + run
    signature = hmac.new(
        os.environ["INTEGRATION_SECRET"].encode(),
        (stamp + ":" + path).encode(),
        hashlib.sha256,
    ).hexdigest()
    with httpx.Client(timeout=5) as c:
        r = c.get(
            "http://127.0.0.1:3014" + path,
            headers={"X-Fleet-Time": stamp, "X-Fleet-Signature": signature},
        )
        r.raise_for_status()
        return r.json()


def execute(job):
    ctx = job.data["context"]
    with db() as s:
        sync = get_sync(s, ctx["run"])
        if not sync:
            return {"expired": True}
        if not sync["data"].get("ingested"):
            save_sync(s, ctx["run"], status="running")
    error = None
    if not sync["data"].get("ingested") and job.kind != "integration_trace":
        try:
            with httpx.Client(timeout=45) as c:
                r = c.post(
                    f"http://127.0.0.1:5678/webhook/{N8N_PREFIX}-{ctx['source']}", json=ctx
                )
                r.raise_for_status()
        except Exception:
            error = "n8n не завершил запрос. Исполнение проверяется по журналу; данные не считаются полученными без ingest."
    for _ in range(6):
        try:
            execution = read_execution(ctx["run"])
            if execution.get("finished"):
                break
        except Exception:
            execution = {}
        time.sleep(0.5)
    with db() as s:
        sync = get_sync(s, ctx["run"])
        if not sync:
            return {"expired": True}
        result = {**sync["data"], "trace": execution.get("trace", [])}
        if not sync["data"].get("ingested"):
            result["error"] = (
                error or "Источник не прошёл нормализацию или проверку подписи"
            )
        save_sync(
            s,
            ctx["run"],
            status="done" if sync["data"].get("ingested") else "failed",
            finished=now(),
            execution_id=str(execution.get("id") or sync["execution_id"] or ""),
            data=result,
        )
    return result


@router.get("/api/v1/integrations")
def listing(request: Request):
    from .api import auth
    from pathlib import Path

    with db() as s:
        sp = auth(s, request)
        if sp.role not in ALLOWED:
            fail("Этот раздел доступен сотрудникам и собственнику", 403)
        runs = [
            dict(x)
            for x in s.execute(
                text(
                    "SELECT * FROM source_sync WHERE space=:sp ORDER BY started DESC LIMIT 40"
                ),
                {"sp": sp.id},
            ).mappings()
        ]
        diffs = [
            {"id": x.id, **x.data}
            for x in s.scalars(
                select(Item).where(
                    Item.space == sp.id,
                    Item.kind == "discrepancy",
                    Item.data["status"].astext == "open",
                )
            )
        ]
        sources = []
        for id in SOURCES:
            last = next((r for r in runs if r["source"] == id), None)
            sources.append(
                {
                    "id": id,
                    "status": last["status"] if last else "pending",
                    "updated": (
                        last["finished"].isoformat()
                        if last and last["status"] == "done" and last["finished"]
                        else None
                    ),
                }
            )
        workflows = {}
        for id in SOURCES:
            f = (
                Path(__file__).parent.parent
                / "n8n"
                / "out"
                / (id + ".json")
            )
            if f.exists():
                w = json.loads(f.read_text())
                workflows[id] = {
                    "nodes": [
                        {
                            "id": n["name"],
                            "title": n["name"],
                            "x": n["position"][0],
                            "y": n["position"][1],
                        }
                        for n in w["nodes"]
                    ],
                    "edges": [
                        [a, e["node"]]
                        for a, c in w["connections"].items()
                        for outputs in c["main"]
                        for e in outputs
                    ],
                }
        return {
            "sources": sources,
            "runs": runs,
            "diffs": diffs,
            "workflows": workflows,
        }
