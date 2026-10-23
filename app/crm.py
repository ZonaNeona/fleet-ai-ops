"""CRM: Bitrix24 for driver hiring and rental requests.

Two transports speak raw Bitrix24 REST — the emulator (built from this visitor's fleet) and a live portal over
an inbound webhook, read-only by an allowlist. Everything above the transport — paging, mapping, the funnel,
the payment reconciliation with the ledger — runs the same code for both. The live portal is used when
BITRIX24_WEBHOOK is set; otherwise the emulator answers in the portal's format (string numbers, `total` /
`next` paging by 50, the `time` block).
"""

import json
import os
import random
import re
import time
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Request
from sqlalchemy import func, select

from .db import Entry, Item, db, now
from .domain import audit, fail
from .seed import add

router = APIRouter()
MSK = ZoneInfo("Europe/Moscow")
PAGE = 50
VIEW = {"owner", "admin", "manager", "finance"}
STUCK_DAYS = 3

LIST = frozenset({"filter", "order", "select", "start"})
READ: dict[str, frozenset[str]] = {
    "user.get": frozenset({"filter", "sort", "order", "start"}),
    "crm.category.list": frozenset({"entityTypeId", "start"}),
    "crm.status.list": LIST,
    "crm.deal.list": LIST,
    "crm.lead.list": LIST,
}
WRITE = {"tasks.task.add": frozenset({"fields"})}  # emulator only: the live portal stays read-only
WEBHOOK = re.compile(r"/rest/\d+/[A-Za-z0-9]+/?")


class ReadOnly(ValueError):
    pass


def validate(method, params, live):
    allowed = READ.get(method) or (None if live else WRITE.get(method))
    if allowed is None:
        raise ReadOnly(f"Метод {method} не разрешён" + (" — портал подключён только на чтение" if live else ""))
    extra = set(params) - allowed
    if extra:
        raise ReadOnly("Недопустимые параметры: " + ", ".join(sorted(extra)))
    if len(json.dumps(params, default=str)) > 16000:
        raise ReadOnly("Слишком большой запрос")


def b24(dt):
    return dt.astimezone(MSK).replace(microsecond=0).isoformat()


def parse(v):
    return datetime.fromisoformat(v) if v else None


# ---------------------------------------------------------------- transports


class Live:
    """Inbound webhook of a real portal. Calls are spaced (2 per second) and errors never echo the URL."""

    mode = "live"

    def __init__(self, url):
        self.url = url.rstrip("/") + "/"
        self.last = 0.0

    def call(self, method, params=None):
        params = params or {}
        validate(method, params, live=True)
        wait = 0.5 - (time.monotonic() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = time.monotonic()
        try:
            r = httpx.post(self.url + method + ".json", json=params, timeout=20)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            raise RuntimeError("Портал Битрикс24 не ответил: " + WEBHOOK.sub("/rest/***/", str(e))[:200]) from None


class Emulator:
    """Answers like a portal, from data generated for this visitor's fleet."""

    mode = "emulator"

    def __init__(self, data, on_write=None):
        self.data = data
        self.on_write = on_write

    def call(self, method, params=None):
        params = params or {}
        validate(method, params, live=False)
        started = time.time()
        extra = {}
        if method == "crm.category.list":
            result = {"categories": self.data["categories"]}
            extra["total"] = len(self.data["categories"])
        elif method == "tasks.task.add":
            task = {"id": str(1000 + len(self.data["tasks"])), **params["fields"], "createdDate": b24(now())}
            self.data["tasks"].append(task)
            if self.on_write:
                self.on_write(self.data)
            result = {"task": task}
        else:
            rows = self._rows(method, params)
            start = int(params.get("start") or 0)
            result = rows[start : start + PAGE]
            extra["total"] = len(rows)
            if start + PAGE < len(rows):
                extra["next"] = start + PAGE
        return {"result": result, **extra,
                "time": {"start": started, "finish": time.time(), "duration": time.time() - started,
                         "processing": 0, "date_start": b24(now()), "date_finish": b24(now())}}

    def _rows(self, method, params):
        collection = {"user.get": "users", "crm.status.list": "statuses", "crm.deal.list": "deals",
                      "crm.lead.list": "leads"}[method]
        gate = "DATE_CREATE" if method in ("crm.deal.list", "crm.lead.list") else None
        moment = now()
        rows = [r for r in self.data[collection] if not gate or parse(r[gate]) <= moment]
        for key, expected in (params.get("filter") or {}).items():
            op = re.match(r"^(>=|<=|>|<|!|)", key).group(1)
            name = key[len(op):]
            values = expected if isinstance(expected, list) else [expected]

            def ok(r, op=op, name=name, values=values, expected=expected):
                actual = r.get(name)
                if op in (">=", "<=", ">", "<"):
                    a, b = str(actual or ""), str(expected)
                    return {">=": a >= b, "<=": a <= b, ">": a > b, "<": a < b}[op]
                hit = str(actual).lower() in [str(v).lower() for v in values] or (isinstance(actual, bool) and str(actual).lower() in [str(v).lower() for v in values])
                return not hit if op == "!" else hit

            rows = [r for r in rows if ok(r)]
        order = params.get("order") or {"ID": "ASC"}
        if isinstance(order, str):
            order = {params.get("sort") or "ID": order}
        for key, direction in reversed(list(order.items())):
            rows = sorted(rows, key=lambda r, k=key: (int(r[k]) if str(r.get(k, "")).isdigit() else str(r.get(k, ""))),
                          reverse=str(direction).upper() == "DESC")
        select_ = params.get("select")
        if select_ and "*" not in select_:
            rows = [{k: v for k, v in r.items() if k in set(select_) | {"ID"}} for r in rows]
        return rows


# ---------------------------------------------------------------- the emulated portal for this fleet

RENTAL = [("NEW", "Новая заявка", "process"), ("PREPARATION", "Подбор авто", "process"),
          ("PREPAYMENT_INVOICE", "Залог выставлен", "process"), ("EXECUTING", "Бронь подтверждена", "process"),
          ("WON", "Авто выдано", "success"), ("LOSE", "Отказ", "failure")]
HIRING = [("C1:NEW", "Отклик", "process"), ("C1:PREPARATION", "Созвон", "process"),
          ("C1:EXECUTING", "Проверка документов", "process"), ("C1:FINAL_INVOICE", "Стажировка", "process"),
          ("C1:WON", "На линии", "success"), ("C1:LOSE", "Отказ", "failure")]
SOURCES = {"WEB": "Сайт", "CALL": "Звонок", "ADVERTISING": "Авито", "RECOMMENDATION": "Рекомендация", "OTHER": "Telegram"}
NAMES = ["Руслан Гарипов", "Сергей Белов", "Тимур Алиев", "Никита Фомин", "Олег Чернов", "Вадим Зуев", "Игорь Кравец",
         "Евгений Пахомов", "Азамат Каримов", "Павел Дроздов", "Максим Ильин", "Роман Лаптев", "Кирилл Осипов",
         "Андрей Мельник", "Денис Гусев", "Артур Валиев", "Станислав Рябов", "Глеб Никитин"]


def dataset(s, sp):
    """Bitrix24 portal content for this space: rental deals mirror its contracts; hiring and leads are generated."""
    rnd = random.Random(sp.id)
    t = now()
    users = [
        {"ID": "1", "NAME": "Ольга", "LAST_NAME": "Смирнова", "WORK_POSITION": "Менеджер по найму водителей", "ACTIVE": True, "UF_DEPARTMENT": [3]},
        {"ID": "7", "NAME": "Артём", "LAST_NAME": "Ковалёв", "WORK_POSITION": "Менеджер проката", "ACTIVE": True, "UF_DEPARTMENT": [4]},
        {"ID": "12", "NAME": "Дарья", "LAST_NAME": "Ершова", "WORK_POSITION": "Руководитель отдела продаж", "ACTIVE": True, "UF_DEPARTMENT": [4]},
    ]
    statuses = []
    for entity, stages in (("DEAL_STAGE", RENTAL), ("DEAL_STAGE_1", HIRING)):
        for i, (sid, name, sem) in enumerate(stages):
            statuses.append({"ID": str(len(statuses) + 1), "ENTITY_ID": entity, "STATUS_ID": sid, "NAME": name,
                             "SORT": str((i + 1) * 10), "SYSTEM": "Y" if sem != "process" else "N", "EXTRA": {"SEMANTICS": sem}})
    deals, n = [], 100
    contracts = s.scalars(select(Item).where(Item.space == sp.id, Item.kind == "contract",
                                             Item.data["direction"].astext == "rental").order_by(Item.code)).all()[:18]
    paid = dict(s.execute(select(Entry.contract, func.sum(Entry.amount)).where(
        Entry.space == sp.id, Entry.kind == "payment", Entry.contract.in_([c.id for c in contracts])).group_by(Entry.contract)).all())
    for i, c in enumerate(contracts):
        car = s.get(Item, c.data["vehicle"])
        days = max(1, (datetime.fromisoformat(c.data["end"]) - datetime.fromisoformat(c.data["start"])).days)
        total = Decimal(c.data["rate"]) * days
        ledger = paid.get(c.id) or Decimal(0)
        crm_paid = ledger + (Decimal(4800) if i in (2, 9) else 0)  # a manager marked a payment the bank never saw
        n += 1
        deals.append({
            "ID": str(n), "TITLE": f"Прокат · {car.data['model']} · {days} дн.", "CATEGORY_ID": "0",
            "STAGE_ID": "WON", "STAGE_SEMANTIC_ID": "S", "OPPORTUNITY": f"{total:.2f}", "CURRENCY_ID": "RUB",
            "ASSIGNED_BY_ID": "7", "SOURCE_ID": rnd.choice(["WEB", "CALL", "ADVERTISING"]),
            "DATE_CREATE": b24(datetime.fromisoformat(c.data["start"] + "T09:00:00+03:00") - timedelta(days=2)),
            "MOVED_TIME": b24(datetime.fromisoformat(c.data["start"] + "T10:00:00+03:00")),
            "UF_CRM_CONTRACT": c.code, "UF_CRM_VEHICLE": car.data["plate"], "UF_CRM_PAID": f"{crm_paid:.2f}",
        })
    for i, (stage, _, sem) in enumerate([RENTAL[0], RENTAL[1], RENTAL[1], RENTAL[2], RENTAL[3], RENTAL[5]]):
        n += 1
        model = rnd.choice(["Haval Jolion", "Geely Preface", "Hongqi H5", "Mercedes-Benz E"])
        created = t - timedelta(hours=rnd.randint(3, 50))
        deals.append({
            "ID": str(n), "TITLE": f"Прокат · {model} · {rnd.choice([2, 3, 7, 14])} дн.", "CATEGORY_ID": "0",
            "STAGE_ID": stage, "STAGE_SEMANTIC_ID": {"process": "P", "success": "S", "failure": "F"}[sem],
            "OPPORTUNITY": f"{rnd.choice([9600, 14400, 33600, 67200]):.2f}", "CURRENCY_ID": "RUB", "ASSIGNED_BY_ID": "7",
            "SOURCE_ID": rnd.choice(["WEB", "CALL"]), "DATE_CREATE": b24(created),
            "MOVED_TIME": b24(created + timedelta(hours=rnd.randint(1, 20))) if stage != "NEW" else b24(created),
            "UF_CRM_CONTRACT": "", "UF_CRM_VEHICLE": "", "UF_CRM_PAID": "0.00",
        })
    names = NAMES[:]
    rnd.shuffle(names)
    plan = ["C1:NEW"] * 4 + ["C1:PREPARATION"] * 3 + ["C1:EXECUTING"] * 3 + ["C1:FINAL_INVOICE"] * 2 + ["C1:WON"] * 3 + ["C1:LOSE"] * 2
    for i, stage in enumerate(plan):
        n += 1
        sem = next(x[2] for x in HIRING if x[0] == stage)
        created = t - timedelta(days=rnd.randint(1, 20), hours=rnd.randint(0, 12))
        stuck = i in (5, 8)  # stuck at «Созвон» and «Проверка документов»
        moved = created + timedelta(hours=rnd.randint(2, 30))
        if stuck:
            moved = t - timedelta(days=STUCK_DAYS + 1 + i % 3)
            created = min(created, moved - timedelta(days=1))
        elif sem == "process":
            moved = t - timedelta(hours=rnd.randint(2, 60))  # open deals that move on time
            created = min(created, moved - timedelta(hours=2))
        elif moved > t:
            moved = t - timedelta(hours=1)
        deals.append({
            "ID": str(n), "TITLE": f"Водитель · {names[i % len(names)]}", "CATEGORY_ID": "1", "STAGE_ID": stage,
            "STAGE_SEMANTIC_ID": {"process": "P", "success": "S", "failure": "F"}[sem], "OPPORTUNITY": "0.00",
            "CURRENCY_ID": "RUB", "ASSIGNED_BY_ID": "1", "SOURCE_ID": rnd.choice(list(SOURCES)),
            "DATE_CREATE": b24(created), "MOVED_TIME": b24(moved),
            "UF_CRM_EXPERIENCE": str(rnd.randint(1, 15)), "UF_CRM_CONTRACT": "", "UF_CRM_VEHICLE": "", "UF_CRM_PAID": "0.00",
        })
    leads = []
    for i in range(12):
        hiring = i % 3 != 2
        # A few leads are dated later today: they appear as the day goes on.
        created = t - timedelta(hours=rnd.randint(1, 70)) if i < 10 else t + timedelta(minutes=40 * (i - 9))
        first, last = names[(i + 5) % len(names)].split()
        leads.append({
            "ID": str(500 + i),
            "TITLE": f"Отклик водителя · стаж {rnd.randint(1, 12)} лет" if hiring
            else f"Заявка на прокат · {rnd.choice(['Haval Jolion', 'Geely Preface'])} на {rnd.choice([2, 3, 7])} дн.",
            "NAME": first, "LAST_NAME": last, "STATUS_ID": rnd.choice(["NEW", "NEW", "IN_PROCESS", "JUNK"]),
            "SOURCE_ID": rnd.choice(list(SOURCES)), "ASSIGNED_BY_ID": "1" if hiring else "7",
            "PHONE": [{"VALUE": f"+7 900 000-{i:02d}-{rnd.randint(10, 99)}", "VALUE_TYPE": "WORK"}],
            "DATE_CREATE": b24(created),
        })
    return {"users": users, "categories": [{"id": 0, "name": "Прокат", "sort": 100, "entityTypeId": 2, "isDefault": "Y"},
                                           {"id": 1, "name": "Найм водителей", "sort": 200, "entityTypeId": 2, "isDefault": "N"}],
            "statuses": statuses, "deals": deals, "leads": leads, "tasks": []}


# ---------------------------------------------------------------- sync, mapping, reconciliation

DEAL_FIELDS = ["ID", "TITLE", "CATEGORY_ID", "STAGE_ID", "STAGE_SEMANTIC_ID", "OPPORTUNITY", "ASSIGNED_BY_ID", "SOURCE_ID",
               "DATE_CREATE", "MOVED_TIME", "UF_CRM_CONTRACT", "UF_CRM_VEHICLE", "UF_CRM_PAID", "UF_CRM_EXPERIENCE"]
LEAD_FIELDS = ["ID", "TITLE", "NAME", "LAST_NAME", "STATUS_ID", "SOURCE_ID", "ASSIGNED_BY_ID", "DATE_CREATE"]


def portal(s, sp):
    """The transport for this space and the item that stores the emulated portal."""
    url = os.getenv("BITRIX24_WEBHOOK")
    if url:
        return Live(url), None
    item = s.scalar(select(Item).where(Item.space == sp.id, Item.kind == "crm_portal"))
    if not item:
        item = add(s, sp.id, "crm_portal", "B24", dataset(s, sp))
        s.flush()

    def save(data):
        item.data = json.loads(json.dumps(data))
        item.version += 1

    return Emulator(json.loads(json.dumps(item.data)), save), item


def sync(s, sp):
    transport, _ = portal(s, sp)
    trace = []

    def call(method, params):
        t = time.perf_counter()
        r = transport.call(method, params)
        rows = r["result"]["categories"] if method == "crm.category.list" else r["result"]
        trace.append({"method": method, "params": {k: v for k, v in params.items() if k != "select"},
                      "ms": round((time.perf_counter() - t) * 1000, 1), "rows": len(rows), "total": r.get("total"),
                      "next": r.get("next")})
        return r

    def everything(method, params):
        start, out = 0, []
        while True:
            r = call(method, {**params, "start": start})
            out += r["result"]
            if r.get("next") is None or int(r["next"]) <= start:
                return out
            start = int(r["next"])

    users = {u["ID"]: f"{u['NAME']} {u['LAST_NAME']}".strip() for u in everything("user.get", {"filter": {"ACTIVE": True}, "sort": "ID", "order": "ASC"})}
    categories = call("crm.category.list", {"entityTypeId": 2})["result"]["categories"]
    statuses = everything("crm.status.list", {"filter": {"ENTITY_ID": ["DEAL_STAGE", "DEAL_STAGE_1"]}, "order": {"SORT": "ASC"}})
    deals = everything("crm.deal.list", {"select": DEAL_FIELDS, "order": {"ID": "ASC"}})
    since = b24(now() - timedelta(days=7))
    leads = everything("crm.lead.list", {"select": LEAD_FIELDS, "filter": {">=DATE_CREATE": since}, "order": {"DATE_CREATE": "DESC"}})

    funnels = []
    for cat in categories:
        entity = "DEAL_STAGE" if int(cat["id"]) == 0 else f"DEAL_STAGE_{cat['id']}"
        stages = [{"id": x["STATUS_ID"], "name": x["NAME"], "semantics": (x.get("EXTRA") or {}).get("SEMANTICS", "process")}
                  for x in statuses if x["ENTITY_ID"] == entity]
        funnels.append({"id": int(cat["id"]), "name": cat["name"], "key": "rental" if int(cat["id"]) == 0 else "hiring", "stages": stages})
    t = now()
    mapped = []
    for d in deals:
        moved = parse(d.get("MOVED_TIME")) or parse(d["DATE_CREATE"])
        days = (t - moved).days
        semantic = d.get("STAGE_SEMANTIC_ID") or "P"
        mapped.append({
            "id": d["ID"], "title": d["TITLE"], "funnel": int(d.get("CATEGORY_ID") or 0), "stage": d["STAGE_ID"],
            "open": semantic == "P", "amount": d.get("OPPORTUNITY") or "0", "manager": users.get(d.get("ASSIGNED_BY_ID"), "—"),
            "source": SOURCES.get(d.get("SOURCE_ID"), d.get("SOURCE_ID") or "—"), "created": d["DATE_CREATE"],
            "days_in_stage": days, "stuck": semantic == "P" and days > STUCK_DAYS,
            "contract": d.get("UF_CRM_CONTRACT") or None, "plate": d.get("UF_CRM_VEHICLE") or None,
            "crm_paid": d.get("UF_CRM_PAID") or "0", "experience": d.get("UF_CRM_EXPERIENCE"),
        })
    reconciliation = reconcile(s, sp, mapped)
    hiring = [d for d in mapped if d["funnel"] == 1]
    won = sum(1 for d in hiring if d["stage"].endswith("WON"))
    snapshot = {
        "mode": transport.mode, "synced_at": t.isoformat(), "funnels": funnels, "deals": mapped,
        "leads": [{"id": x["ID"], "title": x["TITLE"], "name": f"{x.get('NAME') or ''} {x.get('LAST_NAME') or ''}".strip(),
                   "status": x.get("STATUS_ID"), "source": SOURCES.get(x.get("SOURCE_ID"), x.get("SOURCE_ID")),
                   "manager": users.get(x.get("ASSIGNED_BY_ID"), "—"), "created": x["DATE_CREATE"]} for x in leads],
        "reconciliation": reconciliation, "trace": trace,
        "summary": {
            "hiring_total": len(hiring), "hiring_won": won,
            "hiring_conversion": round(won / len(hiring) * 100) if hiring else 0,
            "stuck": sum(1 for d in mapped if d["stuck"]),
            "leads_new": sum(1 for x in leads if x.get("STATUS_ID") == "NEW"),
            "mismatches": sum(1 for r in reconciliation if not r["ok"]),
            "calls": len(trace), "ms": round(sum(x["ms"] for x in trace), 1),
        },
    }
    item = s.scalar(select(Item).where(Item.space == sp.id, Item.kind == "crm"))
    if item:
        item.data = snapshot
        item.version += 1
    else:
        add(s, sp.id, "crm", "CRM", snapshot)
    return snapshot


def reconcile(s, sp, deals):
    """«Paid» in CRM against money that actually reached the ledger, per contract."""
    codes = {d["contract"]: d for d in deals if d["contract"]}
    if not codes:
        return []
    contracts = {c.code: c for c in s.scalars(select(Item).where(Item.space == sp.id, Item.kind == "contract",
                                                                    Item.code.in_(list(codes))))}
    paid = dict(s.execute(select(Entry.contract, func.sum(Entry.amount)).where(
        Entry.space == sp.id, Entry.kind == "payment", Entry.contract.in_([c.id for c in contracts.values()])
    ).group_by(Entry.contract)).all())
    out = []
    for code, d in sorted(codes.items()):
        c = contracts.get(code)
        ledger = paid.get(c.id, Decimal(0)) if c else None
        crm_paid = Decimal(d["crm_paid"])
        diff = crm_paid - ledger if ledger is not None else None
        out.append({"deal": d["id"], "title": d["title"], "contract": code, "contract_id": c.id if c else None,
                    "crm_paid": f"{crm_paid:.2f}", "ledger_paid": f"{ledger:.2f}" if ledger is not None else None,
                    "diff": f"{diff:.2f}" if diff is not None else None, "ok": c is not None and diff == 0,
                    "note": "договора нет в учёте" if not c else "сходится" if diff == 0
                    else "в CRM отмечено больше, чем пришло денег" if diff > 0 else "денег пришло больше, чем отмечено в CRM"})
    return out


# ---------------------------------------------------------------- agent helpers


def pipeline(s, sp, funnel=None):
    item = s.scalar(select(Item).where(Item.space == sp.id, Item.kind == "crm"))
    snap = item.data if item else sync(s, sp)
    out = {"mode": snap["mode"], "synced_at": snap["synced_at"], "summary": snap["summary"], "funnels": []}
    for f in snap["funnels"]:
        if funnel and f["key"] != funnel:
            continue
        deals = [d for d in snap["deals"] if d["funnel"] == f["id"]]
        out["funnels"].append({
            "name": f["name"], "key": f["key"],
            "stages": [{"stage": st["name"], "deals": sum(1 for d in deals if d["stage"] == st["id"])} for st in f["stages"]],
            "stuck": [{"id": d["id"], "title": d["title"], "days_in_stage": d["days_in_stage"], "manager": d["manager"],
                       "stage": next((st["name"] for st in f["stages"] if st["id"] == d["stage"]), d["stage"])}
                      for d in deals if d["stuck"]],
        })
    out["payment_mismatches"] = [r for r in snap["reconciliation"] if not r["ok"]]
    out["new_leads"] = [x for x in snap["leads"] if x["status"] == "NEW"][:10]
    return out


def add_task(s, sp, payload):
    """Confirmed draft from the agent: a task for a manager. Writes only into the emulated portal."""
    transport, _ = portal(s, sp)
    if transport.mode == "live":
        fail("Портал подключён только на чтение: задачи в живом Битрикс24 из демо не создаются", 409)
    r = transport.call("tasks.task.add", {"fields": {
        "TITLE": payload["title"][:200], "DESCRIPTION": payload.get("description", "")[:2000],
        "RESPONSIBLE_ID": payload.get("responsible", "1"),
        "DEADLINE": b24(now() + timedelta(days=1)), "UF_CRM_TASK": [f"D_{payload['deal']}"] if payload.get("deal") else [],
    }})
    return {"code": "B24-T" + r["result"]["task"]["id"], "task": r["result"]["task"]}


# ---------------------------------------------------------------- HTTP


def viewer(s, request):
    from .api import auth

    sp = auth(s, request)
    if sp.role not in VIEW:
        fail("CRM доступна собственнику, менеджеру и финансисту", 403)
    return sp


@router.get("/api/v1/crm")
def crm_view(request: Request):
    with db() as s:
        sp = viewer(s, request)
        item = s.scalar(select(Item).where(Item.space == sp.id, Item.kind == "crm"))
        snap = item.data if item else sync(s, sp)
        portal_item = s.scalar(select(Item).where(Item.space == sp.id, Item.kind == "crm_portal"))
        return {**snap, "tasks": (portal_item.data.get("tasks") if portal_item else []) or []}


@router.post("/api/v1/crm/sync")
def crm_sync(request: Request):
    with db() as s:
        sp = viewer(s, request)
        last = s.scalar(select(Item).where(Item.space == sp.id, Item.kind == "crm"))
        if last and now() - datetime.fromisoformat(last.data["synced_at"]) < timedelta(seconds=5):
            fail("Синхронизация только что выполнялась", 429)
        snap = sync(s, sp)
        audit(s, sp, f"Синхронизация с Битрикс24: {len(snap['deals'])} сделок, {len(snap['leads'])} лидов, "
                     f"расхождений оплат — {snap['summary']['mismatches']}", None, via="crm")
        return snap

