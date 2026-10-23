"""1С: two-way exchange over the standard OData interface.

    GET  <base>/odata/standard.odata/<EntitySet>?$format=json&$filter=…&$top=…&$skip=…
    POST <base>/odata/standard.odata/<EntitySet>?$format=json                 → new document, not posted
    POST <base>/odata/standard.odata/<EntitySet>(guid'<ref>')/Post()          → posts it

Export: last month's accruals per contract go to 1С as «Реализация товаров и услуг», payments as «Поступление
безналичных денежных средств»; the contract and month in the comment make every export idempotent. Import: 1С
documents are read back and reconciled with the ledger both ways. Every visitor has a 1С emulator that speaks the
same protocol (also over HTTP, for n8n or curl); a live base is used when ONEC_ODATA_URL is set.
"""

import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from .db import Entry, Item, Space, db, now
from .domain import fail, today
from .seed import add

router = APIRouter()
VIEW = {"owner", "admin", "finance"}
COUNTERPARTIES = "Catalog_Контрагенты"
VEHICLES = "Catalog_ТранспортныеСредства"
SALES = "Document_РеализацияТоваровУслуг"
PAYMENTS = "Document_ПоступлениеБезналичныхДенежныхСредств"
SETS = (COUNTERPARTIES, VEHICLES, SALES, PAYMENTS)
WRITABLE = (SALES, PAYMENTS)
TERM = re.compile(r"^\s*(\S+)\s+(eq|ne|gt|ge|lt|le)\s+(.+?)\s*$")
POST_PATH = re.compile(r"^(\w+)\(guid'([0-9a-f-]{36})'\)/Post\(\)$")


class ODataError(ValueError):
    pass


# ---------------------------------------------------------------- $filter, as 1С understands the subset we use


def literal(raw):
    raw = raw.strip()
    if raw.startswith("datetime'") and raw.endswith("'"):
        return datetime.fromisoformat(raw[9:-1])
    if raw.startswith("guid'") and raw.endswith("'"):
        return raw[5:-1]
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1].replace("''", "'")
    if raw in ("true", "false"):
        return raw == "true"
    try:
        return float(raw)
    except ValueError:
        raise ODataError(f"Неподдерживаемое значение в $filter: {raw}") from None


def matches(row, expr):
    for part in re.split(r"\s+and\s+", expr.strip()):
        m = TERM.match(part)
        if not m:
            raise ODataError(f"Неподдерживаемое выражение $filter: {part}")
        field, op, expected = m.group(1), m.group(2), literal(m.group(3))
        actual = row.get(field)
        if isinstance(expected, datetime) and isinstance(actual, str):
            actual = datetime.fromisoformat(actual)
        elif isinstance(expected, float) and isinstance(actual, int | float) and not isinstance(actual, bool):
            actual = float(actual)
        if actual is None:
            return False
        try:
            ok = {"eq": actual == expected, "ne": actual != expected, "gt": actual > expected,
                  "ge": actual >= expected, "lt": actual < expected, "le": actual <= expected}[op]
        except TypeError:
            return False
        if not ok:
            return False
    return True


# ---------------------------------------------------------------- transports


class Emulator:
    """A 1С base in a JSON document: the entity sets above, the same query options, POST and Post()."""

    mode = "emulator"

    def __init__(self, data):
        self.data = data
        self.calls = 0

    def get(self, entity_set, params=None):
        params = params or {}
        if entity_set not in SETS:
            raise ODataError(f"Набор {entity_set} не опубликован")
        self.calls += 1
        rows = self.data.get(entity_set, [])
        if params.get("$filter"):
            rows = [r for r in rows if matches(r, params["$filter"])]
        skip, top = int(params.get("$skip") or 0), int(params.get("$top") or 1000)
        return {"odata.metadata": f"…/$metadata#{entity_set}", "value": rows[skip : skip + top]}

    def post(self, entity_set, body):
        self.calls += 1
        m = POST_PATH.match(entity_set)
        if m:
            doc = next((d for d in self.data.get(m.group(1), []) if d["Ref_Key"] == m.group(2)), None)
            if not doc:
                raise ODataError("Документ не найден")
            doc["Posted"] = True
            return {}
        if entity_set not in WRITABLE:
            raise ODataError(f"В набор {entity_set} запись не разрешена")
        rows = self.data.setdefault(entity_set, [])
        number = f"ТП{len(rows) + 1:08d}"
        doc = {**body, "Ref_Key": str(uuid.uuid4()), "Number": number, "Posted": False,
               "DeletionMark": False, "Date": body.get("Date") or now().isoformat(timespec="seconds")}
        rows.append(doc)
        return doc


class Live:
    """A real 1С over HTTP with basic auth. Writes only into the two document sets, and only with ONEC_WRITE=1."""

    mode = "live"

    def __init__(self, url, user, password):
        self.base = url.rstrip("/") + "/odata/standard.odata/"
        self.auth = (user, password)
        self.calls = 0

    def get(self, entity_set, params=None):
        if entity_set not in SETS:
            raise ODataError(f"Набор {entity_set} не входит в список чтения")
        return self._send("GET", entity_set, params={"$format": "json", **(params or {})})

    def post(self, entity_set, body):
        target = POST_PATH.match(entity_set)
        name = target.group(1) if target else entity_set
        if name not in WRITABLE or os.getenv("ONEC_WRITE") != "1":
            raise ODataError("База 1С подключена только на чтение")
        return self._send("POST", entity_set, params={"$format": "json"}, json=body or None)

    def _send(self, method, path, **kw):
        self.calls += 1
        try:
            r = httpx.request(method, self.base + path, auth=self.auth, timeout=30, **kw)
            r.raise_for_status()
            return r.json() if r.content else {}
        except httpx.HTTPError:
            raise ODataError("1С недоступна или вернула ошибку") from None


# ---------------------------------------------------------------- the base this visitor's fleet keeps in 1С


def guid(*parts):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "fleet:" + ":".join(parts)))


def last_month():
    first = today().replace(day=1)
    end = first - timedelta(days=1)
    return end.replace(day=1), end


def base(s, sp):
    """1С as an accountant keeps it: counterparties and cars match the fleet; a bank payment was loaded into 1С
    only, and one act of last month was entered by hand with another amount."""
    start, end = last_month()
    people = s.scalars(select(Item).where(Item.space == sp.id, Item.kind == "client").order_by(Item.code)).all()
    cars = s.scalars(select(Item).where(Item.space == sp.id, Item.kind == "vehicle").order_by(Item.code)).all()
    data = {
        COUNTERPARTIES: [{"Ref_Key": guid(sp.id, p.id), "Description": p.data.get("name", "—"),
                          "ИНН": "", "DeletionMark": False, "Код": p.code} for p in people],
        VEHICLES: [{"Ref_Key": guid(sp.id, v.id), "Description": v.data["model"], "ГосНомер": v.data["plate"],
                    "Код": v.code, "Пробег": v.data.get("mileage")} for v in cars],
        SALES: [], PAYMENTS: [],
    }
    contracts = s.scalars(select(Item).where(Item.space == sp.id, Item.kind == "contract",
                                             Item.data["status"].astext == "active").order_by(Item.code)).all()
    if contracts:
        c = contracts[0]
        data[PAYMENTS].append({  # the bank statement was loaded into 1С, the fleet never saw this money
            "Ref_Key": guid(sp.id, "bank-only"), "Number": "БН00000001", "Date": f"{end.isoformat()}T12:00:00",
            "Posted": True, "Контрагент_Key": guid(sp.id, c.data["client"]), "СуммаДокумента": 12000.0,
            "Комментарий": "Выписка банка: оплата аренды", "DeletionMark": False,
        })
    if len(contracts) > 3:
        c = contracts[3]
        month = start.strftime("%Y-%m")
        data[SALES].append({  # entered by hand before the integration existed, with a typo in the amount
            "Ref_Key": guid(sp.id, "manual-act"), "Number": "ТП00000000", "Date": f"{end.isoformat()}T18:00:00",
            "Posted": True, "Контрагент_Key": guid(sp.id, c.data["client"]), "СуммаДокумента": 1000.0,
            "Комментарий": f"FLEET:{c.code}:{month}:sale", "DeletionMark": False,
        })
    return data


def emulated(s, sp, lock=False):
    item = s.scalar(select(Item).where(Item.space == sp.id, Item.kind == "onec_base"))
    if not item:
        item = add(s, sp.id, "onec_base", "1C", base(s, sp))
        s.flush()
    elif lock:
        s.refresh(item, with_for_update=True)
    return Emulator(json.loads(json.dumps(item.data))), item


def transport_for(s, sp):
    url = os.getenv("ONEC_ODATA_URL")
    if url:
        return Live(url, os.getenv("ONEC_USER", ""), os.getenv("ONEC_PASSWORD", "")), None
    return emulated(s, sp, lock=True)


# ---------------------------------------------------------------- the exchange


def sums(s, sp, kind, start, end):
    rows = s.execute(select(Entry.contract, func.sum(Entry.amount)).where(
        Entry.space == sp.id, Entry.kind == kind, Entry.contract.is_not(None),
        Entry.date >= str(start), Entry.date <= str(end)).group_by(Entry.contract)).all()
    return {c: Decimal(a) for c, a in rows if a}


def exchange(s, sp):
    """Export last month's acts and payments, read them back, reconcile both ways. Safe to run again."""
    started = time.perf_counter()
    onec, item = transport_for(s, sp)
    start, end = last_month()
    month = start.strftime("%Y-%m")
    contracts = {c.id: c for c in s.scalars(select(Item).where(Item.space == sp.id, Item.kind == "contract"))}
    trace, exported, skipped = [], 0, 0

    def call(kind, path, fn, *args):
        t = time.perf_counter()
        result = fn(path, *args)
        trace.append({"call": f"{kind} {path}", "ms": round((time.perf_counter() - t) * 1000, 2)})
        return result

    existing = {}
    for entity in (SALES, PAYMENTS):
        flt = f"Date ge datetime'{start.isoformat()}T00:00:00' and Date le datetime'{end.isoformat()}T23:59:59'"
        for d in call("GET", entity, onec.get, {"$filter": flt})["value"]:
            existing[d.get("Комментарий", "")] = d
    for entity, kind, label in ((SALES, "charge", "sale"), (PAYMENTS, "payment", "payment")):
        for cid, amount in sums(s, sp, kind, start, end).items():
            c = contracts.get(cid)
            if not c:
                continue
            key = f"FLEET:{c.code}:{month}:{label}"
            if key in existing:
                skipped += 1
                continue
            doc = call("POST", entity, onec.post, {
                "Date": f"{end.isoformat()}T20:00:00", "Контрагент_Key": guid(sp.id, c.data["client"]),
                "СуммаДокумента": float(amount), "Комментарий": key,
            })
            call("POST", f"{entity}(guid'{doc['Ref_Key']}')/Post()", onec.post, {})
            exported += 1
    if item is not None:
        item.data = onec.data
        item.version += 1

    # Read back what 1С holds now and reconcile with the ledger.
    flt = f"Date ge datetime'{start.isoformat()}T00:00:00' and Posted eq true"
    in_onec = {entity: call("GET", entity, onec.get, {"$filter": flt})["value"] for entity in (SALES, PAYMENTS)}
    by_code = {c.code: c for c in contracts.values()}
    ledger = {"sale": sums(s, sp, "charge", start, end), "payment": sums(s, sp, "payment", start, end)}
    rows, seen = [], set()
    for entity, label in ((SALES, "sale"), (PAYMENTS, "payment")):
        for d in in_onec[entity]:
            m = re.match(r"^FLEET:([^:]+):(\d{4}-\d{2}):(\w+)$", d.get("Комментарий") or "")
            if not m:
                rows.append({"doc": d["Number"], "kind": label, "contract": None, "onec": d["СуммаДокумента"], "ledger": None,
                             "ok": False, "note": "есть в 1С, в учёте не найдено: " + (d.get("Комментарий") or "без комментария")})
                continue
            c = by_code.get(m.group(1))
            amount = ledger[label].get(c.id) if c else None
            seen.add((label, m.group(1)))
            ok = amount is not None and Decimal(str(d["СуммаДокумента"])) == amount
            rows.append({"doc": d["Number"], "kind": label, "contract": m.group(1), "contract_id": c.id if c else None,
                         "onec": d["СуммаДокумента"], "ledger": float(amount) if amount is not None else None, "ok": ok,
                         "note": "сходится" if ok else "сумма в 1С отличается от учёта — документ введён вручную?"})
    for label, amounts in ledger.items():
        for cid, amount in amounts.items():
            c = contracts.get(cid)
            if c and (label, c.code) not in seen:
                rows.append({"doc": None, "kind": label, "contract": c.code, "contract_id": cid, "onec": None,
                             "ledger": float(amount), "ok": False, "note": "есть в учёте, в 1С нет документа"})
    summary = {
        "mode": onec.mode, "month": month, "exported": exported, "skipped": skipped,
        "documents": sum(len(v) for v in in_onec.values()), "mismatches": sum(1 for r in rows if not r["ok"]),
        "calls": onec.calls, "ms": round((time.perf_counter() - started) * 1000), "at": now().isoformat(),
    }
    report = {"summary": summary, "rows": sorted(rows, key=lambda r: r["ok"]), "trace": trace[:40]}
    run = s.scalar(select(Item).where(Item.space == sp.id, Item.kind == "onec_exchange"))
    if run:
        run.data = report
        run.version += 1
    else:
        add(s, sp.id, "onec_exchange", "1C-EXCHANGE", report)
    return report


# ---------------------------------------------------------------- HTTP: the cabinet and the emulator itself


def viewer(s, request):
    from .api import auth

    sp = auth(s, request)
    if sp.role not in VIEW:
        fail("Обмен с 1С доступен собственнику и финансисту", 403)
    return sp


@router.get("/api/v1/onec")
def onec_view(request: Request):
    with db() as s:
        sp = viewer(s, request)
        run = s.scalar(select(Item).where(Item.space == sp.id, Item.kind == "onec_exchange"))
        from .b24 import key_for

        return {"report": run.data if run else None, "odata": f"/api/onec/{key_for(s, sp)}/odata/standard.odata/",
                "sets": list(SETS)}


@router.post("/api/v1/onec/exchange")
def onec_exchange(request: Request):
    with db() as s:
        sp = viewer(s, request)
        return exchange(s, sp)


@router.api_route("/api/onec/{key}/odata/standard.odata/{path:path}", methods=["GET", "POST"])
async def odata(key: str, path: str, request: Request):
    """The visitor's 1С emulator over HTTP, for n8n, curl or a reviewer: GET with $filter, POST, Post().
    Always the emulator: a live base is never proxied to the outside."""
    from .b24 import space_of

    space = space_of(key)
    if not space:
        return JSONResponse({"odata.error": {"message": {"value": "Неверный ключ"}}}, status_code=401)
    params = dict(request.query_params)
    body = await request.json() if request.method == "POST" and await request.body() else {}
    import anyio

    def run():
        with db() as s:
            sp = s.get(Space, space)
            onec, item = emulated(s, sp, lock=request.method == "POST")
            try:
                result = onec.get(path, params) if request.method == "GET" else onec.post(path, body)
            except ODataError as e:
                return JSONResponse({"odata.error": {"message": {"value": str(e)}}}, status_code=400)
            if request.method == "POST":
                item.data = onec.data
                item.version += 1
            return result

    return await anyio.to_thread.run_sync(run)
