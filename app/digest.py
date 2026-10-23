"""Morning digest for the owner: yesterday's money, debt, cars in the red, and what waits for a person today.

One function builds the text for the bot button, the 09:00 schedule and the cabinet preview. Numbers come from
the same report as the dashboard; nothing here calls a model.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from sqlalchemy import select

from .db import Item, Space, System, db, now
from .domain import today
from .reports import report

router = APIRouter()
MSK = ZoneInfo("Europe/Moscow")
HOUR = 9


def rub(v):
    return f"{Decimal(v):,.0f}".replace(",", " ") + " ₽"


def build(s, sp):
    owner = SimpleNamespace(id=sp.id, role="owner", data=sp.data)
    r = report(s, owner)
    yesterday = str(today() - timedelta(days=1))
    day = next((d for d in r["daily"] if d["date"] == yesterday), None)
    minus = [x for x in r["rows"] if Decimal(x["result"]) < 0]
    items = s.scalars(select(Item).where(Item.space == sp.id, Item.kind.in_(["inbox", "ticket", "crm"]))).all()
    hold = [x for x in items if x.kind == "inbox" and x.data.get("status") in ("review", "mismatch")]
    overdue = [x for x in items if x.kind == "ticket" and x.data.get("status") != "closed"
               and x.data.get("due") and datetime.fromisoformat(x.data["due"]) < now()]
    crm = next((x.data for x in items if x.kind == "crm"), None)
    lines = [
        "🌅 <b>Утренняя сводка</b> · " + datetime.now(MSK).strftime("%d.%m"),
        "",
        f"Вчера: начислено {rub(day['revenue'])}, поступило {rub(day['payments'])}" if day else "Вчера операций не было",
        f"Долг водителей и клиентов: <b>{rub(r['debt'])}</b>",
        f"Загрузка парка: {r['utilization']}% · в ремонте {r['repair']}",
    ]
    if minus:
        worst = sorted(minus, key=lambda x: Decimal(x["result"]))[:3]
        lines.append(f"В минусе за 30 дней: {len(minus)} машин, хуже всех — " +
                     ", ".join(f"{x['code']} ({rub(x['result'])})" for x in worst))
    todo = []
    if hold:
        todo.append(f"документов ждут решения: {len(hold)}")
    if overdue:
        todo.append(f"просроченных заявок сервиса: {len(overdue)}")
    if crm:
        if crm["summary"]["stuck"]:
            todo.append(f"зависших сделок в Битрикс24: {crm['summary']['stuck']}")
        if crm["summary"]["mismatches"]:
            todo.append(f"расхождений оплат CRM ↔ учёт: {crm['summary']['mismatches']}")
    lines += ["", "Сегодня нужен человек: " + "; ".join(todo) if todo else "Срочного на сегодня нет."]
    return "\n".join(lines)


def due_spaces(s):
    """Spaces whose owner linked Telegram and has not had today's digest; checked by the worker each minute."""
    moment = datetime.now(MSK)
    if moment.hour < HOUR:
        return []
    mark = "digest:" + moment.strftime("%Y-%m-%d")
    out = []
    for sp in s.scalars(select(Space).where(Space.data.has_key("tg_chat"), Space.role == "owner")):
        key = mark + ":" + sp.id
        if not s.get(System, key[:60]):
            s.add(System(key=key[:60], data={"at": now().isoformat()}))
            out.append(sp)
    return out


@router.get("/api/v1/digest")
def digest_preview(request: Request):
    from .api import auth

    with db() as s:
        sp = auth(s, request)
        if sp.role not in ("owner", "admin"):
            return {"text": None}
        return {"text": build(s, sp), "schedule": f"каждый день в {HOUR:02d}:00 МСК в Telegram собственника"}
