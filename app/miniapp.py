"""Mini App services. All amounts and authorizations are resolved on the server."""

import hashlib
import json
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select

from .db import Entry, Item, now, uid
from .seed import add


def rental_quote(s, sp, p):
    from .domain import day_range, fail, get, money, own, parse_date, today

    v = get(s, sp, p.get("vehicle"), "vehicle")
    own(s, sp, v)
    if v.data["direction"] not in ("rental", "commercial"):
        fail("Расчёт доступен для проката")
    start, end = parse_date(p.get("start")), parse_date(p.get("end"))
    day_range(start, end)
    if start < today() or end <= start:
        fail("Начало не раньше сегодня; окончание позже начала")
    tariff = s.scalar(
        select(Item)
        .where(
            Item.space == sp.id,
            Item.kind == "tariff",
            Item.data["direction"].astext == v.data["direction"],
            Item.data["effective"].astext <= str(start),
        )
        .order_by(Item.created.desc())
        .limit(1)
    )
    base = money(tariff.data["rate"] if tariff and tariff.data.get("custom") else v.data["rate"])
    days = (end - start).days
    factor = Decimal(".90") if days >= 30 else Decimal(".95") if days >= 7 else Decimal(1)
    driver = str(p.get("additional_driver", "")).strip()[:120]
    daily = money(300 if driver else 0)
    services = money((int(bool(p.get("delivery"))) + int(bool(p.get("collection")))) * 1500)
    rate = money(base * factor)
    result = {
        "vehicle": v.id,
        "start": str(start),
        "end": str(end),
        "days": days,
        "base_rate": str(base),
        "rate": str(rate + daily),
        "rental_rate": str(rate),
        "discount_percent": int((1 - factor) * 100),
        "additional_driver": driver,
        "addons_daily": str(daily),
        "delivery": bool(p.get("delivery")),
        "collection": bool(p.get("collection")),
        "services_amount": str(services),
        "rental_total": str(money((rate + daily) * days)),
        "total": str(money((rate + daily) * days + services)),
        "deposit": "20000.00",
        "tariff_id": tariff.id if tariff else None,
        "tariff_version": tariff.version if tariff else 1,
        "rule": "Сутки с 10:00 до 10:00 МСК; от 7 дней −5%, от 30 дней −10%. Залог отдельно.",
    }
    result["version"] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()[:24]
    return result


def balance(s, sp, contract, kinds):
    return s.scalar(
        select(func.coalesce(func.sum(Entry.amount), 0)).where(
            Entry.space == sp.id, Entry.contract == contract, Entry.kind.in_(kinds)
        )
    )


def own_contract(s, sp, contract):
    from .domain import fail, get

    c = get(s, sp, contract, "contract")
    if sp.role not in ("client", "driver") or c.data["client"] != sp.data.get(sp.role):
        fail("Оплата доступна только по своему договору", 403)
    return c


def fines(s, sp):
    from .domain import allowed_vehicle_ids, money, today

    ids = allowed_vehicle_ids(s, sp)
    records = s.scalars(
        select(Item).where(Item.space == sp.id, Item.kind == "source_record", Item.data["source"].astext == "fines")
    ).all()
    paid = {
        x.data.get("target"): x
        for x in s.scalars(
            select(Item).where(
                Item.space == sp.id,
                Item.kind == "demo_payment",
                Item.data["purpose"].astext == "fine",
                Item.data["status"].astext == "paid",
            )
        ).all()
    }
    result = []
    for x in records:
        if ids is not None and x.data["vehicle"] not in ids:
            continue
        v = x.data.get("values", {})
        amount = money(v.get("fine", 0))
        if amount <= 0:
            continue
        until = v.get("discount_until")
        percent = int(v.get("discount_percent", 0)) if until and str(today()) <= until else 0
        percent = max(0, min(100, percent))
        receipt = paid.get(x.id)
        result.append(
            {
                "id": x.id,
                "vehicle": x.data["vehicle"],
                "external_id": v.get("external_id", x.code),
                "amount": str(amount),
                "due": str(money(amount * (100 - percent) / 100)),
                "discount_percent": percent,
                "discount_until": until,
                "at": x.data.get("at"),
                "source": "Учебный адаптер ГИБДД · n8n",
                "status": "paid" if receipt else "pending",
                "receipt": receipt.id if receipt else None,
                "demo": True,
            }
        )
    return result


def payment_terms(s, sp, purpose, target):
    from .domain import fail, money, require_status

    if purpose == "fine":
        if sp.role != "driver":
            fail("Штрафы доступны водителю", 403)
        fine = next((x for x in fines(s, sp) if x["id"] == target), None)
        if not fine:
            fail("Постановление не найдено", 404)
        if fine["status"] == "paid":
            fail("Штраф уже оплачен", 409)
        return {
            "amount": fine["due"],
            "vehicle": fine["vehicle"],
            "contract": None,
            "client": sp.data["driver"],
            "label": "Учебная оплата штрафа",
            "entry_kind": "fine_payment",
        }
    c = own_contract(s, sp, target)
    if purpose == "deposit":
        if sp.role != "client" or c.data["direction"] not in ("rental", "commercial"):
            fail("Залог доступен клиенту проката", 403)
        require_status(c, ["confirmed", "active"])
        amount = money(c.data["deposit"]) - balance(s, sp, c.id, ["deposit", "deposit_release"])
        kind, label = "deposit", "Учебная оплата возвратного залога"
    elif purpose == "rent":
        if sp.role != "driver":
            fail("Погашение долга доступно водителю", 403)
        require_status(c, ["active", "completed"])
        amount = balance(s, sp, c.id, ["charge"]) - balance(s, sp, c.id, ["payment"])
        kind, label = "payment", "Учебная оплата задолженности"
    else:
        fail("Неизвестное назначение оплаты")
    if amount <= 0:
        fail("Нет суммы к оплате", 409)
    return {
        "amount": str(money(amount)),
        "vehicle": c.data["vehicle"],
        "contract": c.id,
        "client": c.data["client"],
        "label": label,
        "entry_kind": kind,
    }


def payment_command(s, sp, action, p, x):
    from .domain import fail, money, post, update

    if action == "demo_payment.create":
        purpose, target = p.get("purpose"), p.get("target")
        terms = payment_terms(s, sp, purpose, target)
        existing = s.scalars(
            select(Item).where(
                Item.space == sp.id,
                Item.kind == "demo_payment",
                Item.data["target"].astext == target,
                Item.data["purpose"].astext == purpose,
                Item.data["status"].astext == "pending",
            )
        ).all()
        for old in existing:
            if old.data["expires"] > now().isoformat() and old.data["amount"] == terms["amount"]:
                return old, "Учебная оплата ожидает подтверждения"
        x = add(
            s,
            sp.id,
            "demo_payment",
            "DEMO-" + uid()[:8].upper(),
            {
                **terms,
                "purpose": purpose,
                "target": target,
                "status": "pending",
                "demo": True,
                "expires": (now() + timedelta(minutes=10)).isoformat(),
            },
        )
        return x, "Создана учебная оплата"
    if not x or x.kind != "demo_payment" or x.data.get("client") != sp.data.get(sp.role):
        fail("Учебная оплата не найдена", 404)
    if x.data["status"] == "paid":
        return x, "Учебная оплата уже проведена"
    if x.data["expires"] < now().isoformat():
        fail("Время оплаты истекло. Получите новый расчёт.", 409)
    terms = payment_terms(s, sp, x.data["purpose"], x.data["target"])
    if terms["amount"] != x.data["amount"]:
        fail("Сумма изменилась. Получите новый расчёт.", 409)
    post(
        s,
        sp,
        terms["entry_kind"],
        money(terms["amount"]),
        terms["vehicle"],
        terms["contract"],
        terms["label"],
        key="demo-payment:" + x.id,
        demo=True,
        receipt=x.id,
        purpose=x.data["purpose"],
    )
    update(x, status="paid", paid_at=now().isoformat())
    return x, "Учебная оплата проведена · квитанция готова"


def validate_photos(s, sp, photos, image_only=True):
    from .domain import fail, file_access, get

    if not isinstance(photos, list) or len(photos) > 8:
        fail("Допустимо не более 8 файлов")
    for fid in photos:
        f = get(s, sp, fid, "file")
        if not file_access(s, sp, f):
            fail("Нет доступа к файлу", 403)
        if image_only and f.data.get("ext") not in (".jpg", ".jpeg", ".png"):
            fail("Загрузите фотографию JPEG или PNG")


def inspection_command(s, sp, p):
    from .domain import fail, get, sla_due, update

    v = get(s, sp, p.get("vehicle"), "vehicle")
    c = s.scalar(
        select(Item).where(
            Item.space == sp.id,
            Item.kind == "contract",
            Item.data["vehicle"].astext == v.id,
            Item.data["client"].astext == sp.data.get("driver"),
            Item.data["status"].astext == "active",
        )
    )
    if sp.role != "driver" or not c:
        fail("Осмотр доступен по действующему договору водителя", 403)
    shots = p.get("shots", {})
    if not isinstance(shots, dict) or set(shots) != {"front", "rear", "left", "right"} or len(set(shots.values())) != 4:
        fail("Нужны четыре разных фото: спереди, сзади, слева и справа")
    photos = list(shots.values())
    validate_photos(s, sp, photos)
    try:
        mileage, fuel = int(p.get("mileage", -1)), int(p.get("fuel", -1))
    except (TypeError, ValueError):
        fail("Проверьте пробег и топливо")
    if mileage < v.data["mileage"] or mileage > 3000000 or fuel not in range(101):
        fail("Проверьте пробег и топливо")
    notes = str(p.get("notes", "")).strip()[:2000]
    x = add(
        s,
        sp.id,
        "inspection",
        "SHIFT-" + uid()[:7],
        {
            "vehicle": v.id,
            "contract": c.id,
            "client": sp.data["driver"],
            "subtype": "pre_shift",
            "date": now().isoformat(),
            "mileage": mileage,
            "fuel": fuel,
            "damage": notes or "Замечаний нет",
            "photos": photos,
            "shots": shots,
        },
    )
    update(v, mileage=mileage, fuel=fuel, last_driver_inspection=x.id)
    if notes:
        ticket = add(
            s,
            sp.id,
            "ticket",
            "SRV-" + uid()[:6].upper(),
            {
                "vehicle": v.id,
                "contract": c.id,
                "title": "Замечания предсменного осмотра",
                "description": notes,
                "inspection": x.id,
                "status": "new",
                "priority": "technical",
                "assignee": "Технический отдел",
                "estimate": "0",
                "payer": "company",
                "opened": now().isoformat(),
                "due": sla_due("technical").isoformat(),
                "photos": photos,
            },
        )
        update(x, ticket=ticket.id)
    return x, "Предсменный осмотр сохранён" + (" · создано обращение" if notes else "")
