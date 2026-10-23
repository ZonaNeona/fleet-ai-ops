from decimal import Decimal
from datetime import timedelta
from sqlalchemy import select, func, case, text, tuple_, or_
from .db import Entry, Booking
from .domain import visible, allowed_vehicle_ids, money, today, parse_date, day_range


def scope(s, sp):
    q = select(Entry).where(Entry.space == sp.id)
    if sp.role in ("driver", "client"):
        ids = [x.id for x in visible(s, sp, "contract")]
        q = q.where(
            Entry.contract.in_(ids),
            Entry.kind.in_(["charge", "payment", "deposit", "deposit_release", "cash_refund"]),
        )
    elif sp.role == "investor":
        q = q.where(Entry.vehicle.in_(allowed_vehicle_ids(s, sp)))
    elif sp.role not in ("owner", "finance", "admin"):
        q = q.where(False)
    return q


def entries(s, sp, start=None, end=None, vehicle=None, contract=None, limit=None, offset=0):
    q = scope(s, sp)
    if start:
        q = q.where(Entry.date >= start)
    if end:
        q = q.where(Entry.date <= end)
    if vehicle:
        q = q.where(Entry.vehicle == vehicle)
    if contract:
        q = q.where(Entry.contract == contract)
    q = q.order_by(Entry.date.desc(), Entry.id)
    if limit:
        q = q.limit(limit).offset(offset)
    return s.scalars(q).all()


def ledger_row(e):
    return {
        "id": e.id,
        "vehicle": e.vehicle,
        "contract": e.contract,
        "kind": e.kind,
        "amount": str(e.amount),
        "date": e.date,
        **e.data,
    }


def payment_allocation(s, sp, contract):
    rows = s.scalars(
        scope(s, sp)
        .where(Entry.contract == contract, Entry.kind.in_(["charge", "payment"]))
        .order_by(Entry.date, Entry.id)
    ).all()
    credit = max(
        Decimal(0),
        sum((e.amount if e.kind == "payment" else -min(e.amount, Decimal(0)) for e in rows), Decimal(0)),
    )
    result = []
    for e in rows:
        if e.kind != "charge" or e.amount <= 0:
            continue
        covered = min(credit, e.amount)
        credit -= covered
        result.append(
            {
                "id": e.id,
                "date": e.date,
                "reason": e.data.get("reason", "Начисление"),
                "amount": str(e.amount),
                "covered": str(covered),
                "remaining": str(e.amount - covered),
            }
        )
    return {
        "rows": result,
        "advance": str(credit),
        "method": "FIFO: оплаты и корректировки погашают самые ранние начисления. Сторно оплаты уменьшает покрытие; остаток является авансом. Залоги исключены.",
    }


def report(s, sp, start=None, end=None, branch=None, direction=None):
    s.execute(text("SET LOCAL statement_timeout='4000ms'"))
    s.execute(text("SET LOCAL work_mem='16MB'"))
    start = start or str(today() - timedelta(days=29))
    end = end or str(today())
    days = day_range(start, end)
    all_vehicles = visible(s, sp, "vehicle")
    vehicles = [
        v
        for v in all_vehicles
        if (not branch or v.data["branch"] == branch) and (not direction or v.data["direction"] == direction)
    ]
    ids = {v.id for v in vehicles}
    by = {}
    daily = {}
    types = {}
    base = scope(s, sp).subquery()
    global_overhead = Decimal(0)
    grouped = (
        select(
            base.c.vehicle, base.c.date, base.c.kind, func.sum(base.c.amount), func.grouping(base.c.vehicle)
        )
        .where(base.c.date >= start, base.c.date <= end, or_(base.c.vehicle.in_(ids), base.c.vehicle == None))
        .group_by(func.grouping_sets(tuple_(base.c.vehicle, base.c.kind), tuple_(base.c.date, base.c.kind)))
    )
    for vehicle, d, kind, amount, is_daily in s.execute(grouped):
        if is_daily:
            if kind not in ("charge", "payment", "expense", "bonus"):
                continue
            row = daily.setdefault(
                d, {"date": d, "revenue": Decimal(0), "payments": Decimal(0), "expenses": Decimal(0)}
            )
            row["revenue" if kind == "charge" else "payments" if kind == "payment" else "expenses"] += amount
        else:
            if vehicle is None and kind == "overhead":
                global_overhead += amount
            if vehicle in ids:
                types[kind] = types.get(kind, Decimal(0)) + amount
                by.setdefault(vehicle, {})[kind] = amount
    downtime = {}
    for ticket in visible(s, sp, "ticket"):
        d = ticket.data
        if not d.get("repair_started"):
            continue
        a = max(parse_date(start), parse_date(d["repair_started"][:10]))
        b = min(parse_date(end), parse_date((d.get("closed_at") or str(today()))[:10]))
        if b >= a:
            downtime.setdefault(d["vehicle"], set()).update(
                a + timedelta(days=i) for i in range((b - a).days + 1)
            )
    weights = {v.id: max(0, len(days) - len(downtime.get(v.id, set()))) for v in all_vehicles}
    total_weight = sum(weights.values())
    allocations = {
        v.id: money(global_overhead * weights[v.id] / total_weight) if total_weight else Decimal(0)
        for v in all_vehicles
    }
    if all_vehicles and total_weight:
        last = next(v.id for v in reversed(all_vehicles) if weights[v.id])
        allocations[last] += global_overhead - sum(allocations.values())
    overhead = sum((allocations.get(id, Decimal(0)) for id in ids), Decimal(0))
    rows = []
    historic = (
        select(base)
        .where(base.c.date <= end, base.c.vehicle.in_(ids), base.c.kind.in_(["charge", "payment"]))
        .cte("historic")
    )
    positive = (historic.c.kind == "charge") & (historic.c.amount > 0)
    cutoff7 = str(parse_date(end) - timedelta(days=7))
    cutoff30 = str(parse_date(end) - timedelta(days=30))
    totals = select(
        historic.c.contract,
        historic.c.vehicle,
        func.sum(case((historic.c.kind == "charge", historic.c.amount), else_=0)).label("charges"),
        func.sum(case((historic.c.kind == "payment", historic.c.amount), else_=0)).label("paid"),
        func.sum(
            case(((historic.c.kind == "charge") & (historic.c.amount < 0), historic.c.amount), else_=0)
        ).label("corrections"),
        func.sum(case((positive & (historic.c.date < cutoff30), historic.c.amount), else_=0)).label("old"),
        func.sum(
            case(
                (positive & (historic.c.date >= cutoff30) & (historic.c.date < cutoff7), historic.c.amount),
                else_=0,
            )
        ).label("middle"),
        func.sum(case((positive & (historic.c.date >= cutoff7), historic.c.amount), else_=0)).label("recent"),
    ).group_by(historic.c.contract, historic.c.vehicle)
    debt = Decimal(0)
    debt_by = {}
    aging = {"1–7": Decimal(0), "8–30": Decimal(0), "31+": Decimal(0)}
    for row in s.execute(totals):
        amount = max(Decimal(0), row.charges - row.paid)
        debt += amount
        debt_by[row.vehicle] = debt_by.get(row.vehicle, Decimal(0)) + amount
        credit = max(Decimal(0), row.paid - row.corrections)
        for bucket, due in [("31+", row.old), ("8–30", row.middle), ("1–7", row.recent)]:
            covered = min(credit, due)
            credit -= covered
            aging[bucket] += min(amount, due - covered)
            amount -= min(amount, due - covered)
    for v in vehicles:
        r = by.get(v.id, {})
        rev = r.get("charge", Decimal(0))
        paid = r.get("payment", Decimal(0))
        expense = r.get("expense", Decimal(0)) + r.get("bonus", Decimal(0))
        direct = rev - expense
        allocated = allocations.get(v.id, Decimal(0))
        rows.append(
            {
                "id": v.id,
                "code": v.code,
                "model": v.data["model"],
                "branch": v.data["branch"],
                "direction": v.data["direction"],
                "revenue": str(rev),
                "payments": str(paid),
                "expenses": str(expense),
                "direct_result": str(direct),
                "overhead": str(allocated),
                "result": str(direct - allocated),
                "debt": str(debt_by.get(v.id, 0)),
                "investor": v.data.get("investor"),
                "available_days": weights[v.id],
                "downtime_days": len(downtime.get(v.id, set())),
            }
        )
    rates = {v.id: money(v.data["rate"]) for v in vehicles}
    for row in rows:
        row["lost_revenue_estimate"] = str(money(rates[row["id"]] * row["downtime_days"]))
    rows.sort(key=lambda x: Decimal(x["result"]), reverse=True)
    active = (
        set(s.scalars(select(Booking.vehicle).where(Booking.space == sp.id, Booking.state == "active")).all())
        & ids
    )
    revenue = types.get("charge", Decimal(0))
    expenses = types.get("expense", Decimal(0)) + types.get("bonus", Decimal(0))
    return {
        "start": start,
        "end": end,
        "fleet": len(vehicles),
        "active": len(active),
        "ready": sum(v.data["status"] == "ready" and v.id not in active for v in vehicles),
        "repair": sum(v.data["status"] == "repair" for v in vehicles),
        "utilization": round(100 * len(active) / max(1, len(vehicles)), 1),
        "revenue": str(revenue),
        "payments": str(types.get("payment", 0)),
        "expenses": str(expenses),
        "profit": str(revenue - expenses - overhead),
        "overhead": str(overhead),
        "debt": str(debt),
        "aging": {k: str(v) for k, v in aging.items()},
        "deposits": str(types.get("deposit", 0) + types.get("deposit_release", 0)),
        "rows": rows,
        "daily": [
            {k: str(v) if isinstance(v, Decimal) else v for k, v in row.items()}
            for _, row in sorted(daily.items())
        ],
        "methodology": "Начисления и поступления разделены. Прямой результат = начисления − расходы − бонусы. Общие расходы распределяются по доступным автомобиледням группы за вычетом зафиксированного простоя. Фильтры показывают долю выбранных автомобилей. Долг и возраст — на конец периода, погашение FIFO. Залоги и ожидаемое страховое возмещение не являются выручкой.",
    }
