"""«Сделать сейчас»: what in the fleet needs a person today, each with the reason and the next action.

Rules over the space's own data — no model, no stored list: every signal is recomputed from the ledger, the service
tickets, the Bitrix24 snapshot and the call reviews, so it disappears as soon as the cause is fixed.

    debt-silent      a driver owes more than two days of rent and has not paid for three days
    rental-overdue   a rental ended, the contract is still open (the car is not back or not closed)
    ticket-overdue   a service ticket is past its deadline
    hiring-stuck     a candidate sits on a hiring stage longer than the norm
    crm-paid-gap     a manager marked a deal paid, the money never reached the ledger
    call-low         a dispatcher call scored below the threshold
"""

from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from .db import Entry, Item, System, db, now
from .domain import fail, today

router = APIRouter()
VIEW = {"owner", "admin", "manager", "finance"}
CALL_THRESHOLD = 60
RULES = {
    "debt-silent": "Долг без оплаты",
    "rental-overdue": "Аренда закончилась, договор открыт",
    "ticket-overdue": "Заявка сервиса просрочена",
    "hiring-stuck": "Кандидат завис в найме",
    "crm-paid-gap": "Оплачено в CRM, денег нет",
    "call-low": "Звонок ниже нормы",
}
WEIGHT = {"rental-overdue": 0, "ticket-overdue": 1, "crm-paid-gap": 2, "debt-silent": 3, "hiring-stuck": 4, "call-low": 5}


def rub(v) -> str:
    return f"{Decimal(v):,.0f}".replace(",", " ") + " ₽"


def compute(s, sp, rule: str | None = None, limit: int = 30):
    out = []
    items = s.scalars(select(Item).where(Item.space == sp.id, Item.kind.in_(["contract", "client", "vehicle", "ticket", "crm"]))).all()
    by_id = {x.id: x for x in items}
    contracts = [x for x in items if x.kind == "contract" and x.data.get("status") == "active"]
    sums = {(c, k): Decimal(a) for c, k, a in s.execute(
        select(Entry.contract, Entry.kind, func.sum(Entry.amount)).where(
            Entry.space == sp.id, Entry.kind.in_(["charge", "payment"]),
            Entry.contract.in_([c.id for c in contracts])).group_by(Entry.contract, Entry.kind)).all()}
    paid_at = dict(s.execute(select(Entry.contract, func.max(Entry.date)).where(
        Entry.space == sp.id, Entry.kind == "payment", Entry.contract.in_([c.id for c in contracts])
    ).group_by(Entry.contract)).all())
    for c in contracts:
        person = by_id.get(c.data.get("client"))
        name = person.data.get("name", "—") if person else "—"
        car = by_id.get(c.data.get("vehicle"))
        plate = car.data.get("plate", "") if car else ""
        if c.data.get("direction") in ("taxi", "buyout"):
            debt = sums.get((c.id, "charge"), Decimal(0)) - sums.get((c.id, "payment"), Decimal(0))
            last = paid_at.get(c.id)
            quiet = (today() - datetime.fromisoformat(last).date()).days if last else 99
            if debt > Decimal(c.data["rate"]) * 2 and quiet >= 3:
                out.append({"rule": "debt-silent", "target": c.id, "code": c.code,
                            "title": f"{name} · {c.code}", "reason": f"долг {rub(debt)}, оплат нет {quiet} дн.",
                            "action": "Позвонить водителю и договориться о графике погашения; при отказе — по регламенту удержания."})
        elif c.data.get("end") and c.data["end"] < str(today()):
            late = (today() - datetime.fromisoformat(c.data["end"]).date()).days
            out.append({"rule": "rental-overdue", "target": c.id, "code": c.code,
                        "title": f"{name} · {plate or c.code}", "reason": f"аренда закончилась {late} дн. назад, договор не закрыт",
                        "action": "Связаться с клиентом: продление или возврат машины; закрыть договор после осмотра."})
    for t in (x for x in items if x.kind == "ticket"):
        due = t.data.get("due")
        if t.data.get("status") not in ("closed", "done") and due and datetime.fromisoformat(due) < now():
            hours = int((now() - datetime.fromisoformat(due)).total_seconds() // 3600)
            car = by_id.get(t.data.get("vehicle"))
            out.append({"rule": "ticket-overdue", "target": t.id, "code": t.code,
                        "title": f"{t.code} · {t.data.get('title', '')}",
                        "reason": f"срок истёк {hours} ч назад" if hours else "срок только что истёк",
                        "action": f"Назначить мастера или согласовать новый срок{' по ' + car.data['plate'] if car else ''}."})
    crm = next((x.data for x in items if x.kind == "crm"), None)
    if crm:
        for d in crm.get("deals", []):
            if d.get("stuck") and d.get("funnel") == 1:
                out.append({"rule": "hiring-stuck", "target": None, "code": "B24 #" + d["id"], "title": d["title"],
                            "reason": f"{d['days_in_stage']} дн. на стадии без движения, ответственный {d['manager']}",
                            "action": "Позвонить кандидату сегодня или закрыть сделку с причиной отказа."})
        for r in crm.get("reconciliation", []):
            if not r.get("ok"):
                out.append({"rule": "crm-paid-gap", "target": r.get("contract_id"), "code": r["contract"],
                            "title": f"{r['title']} · {r['contract']}", "reason": r["note"],
                            "action": "Проверить выписку; если денег нет — вернуть сделке статус «не оплачено» и связаться с клиентом."})
    from .calls import audio, cache_key, index

    for call in index():
        review = s.get(System, cache_key(call["id"], audio(call["id"])))
        score = (review.data or {}).get("score") if review else None
        if score is not None and score < CALL_THRESHOLD:
            out.append({"rule": "call-low", "target": None, "code": call["id"], "title": call.get("title", call["id"]),
                        "reason": f"оценка {score}/100 при норме {CALL_THRESHOLD}",
                        "action": "Разобрать запись с диспетчером на планёрке: что пропущено по чек-листу."})
    if rule:
        out = [x for x in out if x["rule"] == rule]
    out.sort(key=lambda x: WEIGHT[x["rule"]])
    for x in out:
        x["label"] = RULES[x["rule"]]
    return out[:limit]


def summary(rows):
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["rule"]] = counts.get(r["rule"], 0) + 1
    return [{"rule": k, "label": RULES[k], "count": counts[k]} for k in sorted(counts, key=lambda k: WEIGHT[k])]


@router.get("/api/v1/signals")
def signals(request: Request, rule: str | None = None):
    from .api import auth

    with db() as s:
        sp = auth(s, request)
        if sp.role not in VIEW:
            fail("Сигналы видят собственник, менеджер и финансист", 403)
        rows = compute(s, sp, rule if rule in RULES else None, limit=60)
        return {"at": now().isoformat(), "summary": summary(rows), "rows": rows, "rules": RULES,
                "window": str(today() - timedelta(days=3))}
