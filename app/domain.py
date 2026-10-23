"""Transactional application commands shared by HTTP, Telegram and jobs."""

import hashlib, json, math
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from sqlalchemy import select, func, text
from psycopg.types.range import Range
from fastapi import HTTPException
from .db import Item, Entry, Event, Job, Booking, Receipt, Space, now, uid
from .seed import add, BRANCHES

STAFF = {"owner", "manager", "service", "finance", "screening", "admin"}
READ = {
    "manager": {
        "vehicle",
        "client",
        "contract",
        "ticket",
        "inspection",
        "referral",
        "tariff",
        "knowledge",
        "document",
    },
    "service": {"vehicle", "ticket", "inspection", "knowledge", "document"},
    "screening": {"client", "knowledge"},
    "finance": {
        "vehicle",
        "client",
        "contract",
        "ticket",
        "investor",
        "statement",
        "referral",
        "import",
        "tariff",
        "knowledge",
        "document",
        "inspection",
    },
}
WRITE = {
    "demo_payment.create": {"client", "driver"},
    "demo_payment.confirm": {"client", "driver"},
    "driver.inspection": {"driver"},
    "contract.approve_terms": {"finance"},
    "ticket.schedule": {"service", "manager"},
    "ticket.substitute": {"manager"},
    "client.create": {"manager", "client"},
    "client.documents": {"manager", "screening", "driver", "client"},
    "client.review": {"screening"},
    "contract.create": {"manager", "client", "driver"},
    "contract.confirm": {"manager"},
    "contract.issue": {"manager"},
    "contract.return": {"manager"},
    "contract.extend": {"manager"},
    "contract.cancel": {"manager", "client"},
    "contract.holiday": {"driver", "manager"},
    "contract.approve_holiday": {"finance"},
    "contract.close_quote": {"finance"},
    "contract.close": {"finance"},
    "contract.close_request": {"driver", "manager"},
    "contract.schedule": {"driver", "manager"},
    "contract.approve_schedule": {"finance"},
    "vehicle.inspect": {"manager", "service"},
    "vehicle.transfer": {"manager"},
    "ticket.create": {"manager", "driver", "client", "service"},
    "ticket.estimate": {"service"},
    "ticket.approve": {"finance", "investor"},
    "ticket.start": {"service"},
    "ticket.complete": {"service"},
    "ticket.release": {"service"},
    "payment.create": {"finance"},
    "entry.reverse": {"finance"},
    "deposit.refund": {"finance"},
    "deposit.withhold": {"finance"},
    "period.close": {"finance"},
    "period.reopen": {"finance"},
    "owner.statement": {"finance"},
    "owner.approve": {"finance"},
    "owner.pay": {"finance"},
    "referral.approve": {"finance"},
    "referral.create": {"driver", "manager"},
    "tariff.create": {"admin"},
    "import.commit": {"finance"},
    "import.resolve": {"finance"},
}


def fail(message, status=400):
    raise HTTPException(status, message)


def today():
    return now().astimezone(ZoneInfo("Europe/Moscow")).date()


def sla_due(priority):
    if priority in ("urgent", "technical"):
        return now() + timedelta(minutes=15 if priority == "urgent" else 120)
    day = today() + timedelta(days=1)
    while day.weekday() > 4:
        day += timedelta(days=1)
    return datetime.combine(day, datetime.min.time(), ZoneInfo("Europe/Moscow")).replace(hour=18)


def money(v):
    try:
        d = Decimal(str(v))
        if not d.is_finite() or abs(d) > Decimal("999999999"):
            fail("Некорректная сумма")
        return d.quantize(Decimal(".01"))
    except (InvalidOperation, ValueError, TypeError):
        fail("Некорректная сумма")


def positive(v):
    d = money(v)
    if d <= 0:
        fail("Сумма должна быть положительной")
    return d


def parse_date(v):
    try:
        return date.fromisoformat(str(v))
    except (ValueError, TypeError):
        fail("Укажите дату в формате ГГГГ-ММ-ДД")


def day_range(start, end):
    a, b = parse_date(start), parse_date(end)
    if b < a or (b - a).days > 1096:
        fail("Допустимый период — от 1 дня до 3 лет")
    return [a + timedelta(days=i) for i in range((b - a).days + 1)]


def get(s, sp, id, kind=None, lock=False):
    q = select(Item).where(Item.space == sp.id, Item.id == id)
    if kind:
        q = q.where(Item.kind == kind)
    if lock:
        q = q.with_for_update()
    x = s.scalar(q)
    if not x:
        fail("Объект не найден", 404)
    return x


def allowed_vehicle_ids(s, sp):
    if sp.role in STAFF:
        return None
    vs = s.scalars(select(Item).where(Item.space == sp.id, Item.kind == "vehicle")).all()
    if sp.role == "investor":
        return {x.id for x in vs if x.data.get("investor") == sp.data.get("investor")}
    cid = sp.data.get(sp.role)
    return {
        x.data["vehicle"]
        for x in s.scalars(select(Item).where(Item.space == sp.id, Item.kind == "contract")).all()
        if x.data["client"] == cid
    }


def cansee(s, sp, x):
    if sp.role in ("owner", "admin"):
        return True
    if x.kind == "demo_payment":
        return sp.role == "finance" or x.data.get("client") == sp.data.get(sp.role)
    if sp.role in READ:
        return x.kind in READ[sp.role]
    d = x.data
    if x.kind == "source_record":
        return sp.role == "driver" and d.get("source") == "fines" and d.get("vehicle") in allowed_vehicle_ids(s, sp)
    if x.kind == "client":
        return x.id == sp.data.get(sp.role)
    if x.kind == "investor":
        return sp.role == "investor" and x.id == sp.data.get("investor")
    if x.kind == "knowledge":
        return sp.role in d.get("roles", [])
    if x.kind == "tariff":
        return True
    if x.kind == "vehicle":
        return (
            sp.role == "client"
            and d["direction"] in ("rental", "commercial")
            or x.id in allowed_vehicle_ids(s, sp)
        )
    if x.kind == "contract":
        return (
            d.get("client") == sp.data.get(sp.role)
            if sp.role != "investor"
            else d.get("vehicle") in allowed_vehicle_ids(s, sp)
        )
    if x.kind == "statement":
        return sp.role == "investor" and d.get("investor") == sp.data.get("investor")
    if x.kind == "referral":
        return sp.role == "driver" and d.get("client") == sp.data.get("driver")
    if x.kind in ("ticket", "document", "inspection"):
        return d.get("vehicle") in allowed_vehicle_ids(s, sp)
    return False


def visible(s, sp, kind):
    if sp.role in READ and kind not in READ[sp.role]:
        return []
    xs = s.scalars(select(Item).where(Item.space == sp.id, Item.kind == kind).order_by(Item.code)).all()
    if sp.role in STAFF:
        return xs
    ids = allowed_vehicle_ids(s, sp)
    if kind == "vehicle":
        return [
            x
            for x in xs
            if x.id in ids or sp.role == "client" and x.data["direction"] in ("rental", "commercial")
        ]
    if kind == "contract":
        return (
            [x for x in xs if x.data.get("vehicle") in ids]
            if sp.role == "investor"
            else [x for x in xs if x.data.get("client") == sp.data.get(sp.role)]
        )
    if kind in ("ticket", "document", "inspection"):
        return [x for x in xs if x.data.get("vehicle") in ids]
    return [x for x in xs if cansee(s, sp, x)]


def serialize(x):
    return {"id": x.id, "code": x.code, "version": x.version, "kind": x.kind, **x.data}


def file_access(s, sp, x):
    if sp.role in ("owner", "admin") or x.data.get("creator_role") == sp.role:
        return True
    if any(x.id == doc.get("file") for c in visible(s, sp, "client")
           for doc in c.data.get("document_files", []) if isinstance(doc, dict)):
        return True
    return any(
        x.id in parent.data.get("photos", [])
        for kind in ("ticket", "inspection")
        for parent in visible(s, sp, kind)
    )


def update(x, **kw):
    x.data = {**x.data, **kw}
    x.version += 1


def audit(s, sp, title, target=None, **data):
    s.add(Event(space=sp.id, title=title, target=target, role=sp.role, data=data))
    s.add(
        Job(
            space=sp.id,
            kind="notify",
            # via: откуда пришла команда; действия из бота уже получили ответ в чате — дубль не шлём
            data={"title": title, "target": target, "role": sp.role, "via": data.get("via")},
            result={},
        )
    )


def check_open(sp, d):
    if str(d)[:7] in sp.data.get("closed_months", []):
        fail("Период закрыт. Финансист должен переоткрыть месяц.", 409)


def post(s, sp, kind, amount, vehicle=None, contract=None, reason="", key=None, d=None, **data):
    d = str(parse_date(d or today()))
    check_open(sp, d)
    e = Entry(
        id=uid(),
        space=sp.id,
        kind=kind,
        amount=money(amount),
        vehicle=vehicle,
        contract=contract,
        date=d,
        key=key or uid(),
        data={"reason": reason, **data},
    )
    s.add(e)
    return e


def calendar(c, start=None, end=None):
    d = c.data if hasattr(c, "data") else c
    result = []
    for day in day_range(start or d["start"], end or d["end"]):
        if d.get("direction") in ("rental", "commercial") and str(day) >= d["end"]:
            continue
        schedule = d["schedule"]
        for h in reversed(d.get("schedule_history", [])):
            if str(day) <= h["until"]:
                schedule = h["schedule"]
        off = d.get("direction") in ("taxi", "buyout") and (
            (schedule == "6/1" and day.weekday() == 6) or (schedule == "5/2" and day.weekday() >= 5)
        )
        exempt = day.isoformat() in d.get("holidays", [])
        free = d.get("free_first", False) and str(day) == d["start"]
        reason = (
            "Согласованное освобождение"
            if exempt
            else "Первый день бесплатно" if free else "Выходной по графику" if off else "Аренда по договору"
        )
        result.append(
            {
                "date": str(day),
                "amount": str(money(0 if exempt or free or off else d["rate"])),
                "reason": reason,
            }
        )
    if d.get("direction") == "buyout" and (end or d["end"]) >= d["end"]:
        result.append(
            {
                "date": d["end"],
                "amount": str(money(d.get("final_payment", 0))),
                "reason": "Завершающий выкупной платёж",
            }
        )
    return result


def bill(s, sp, c, until=None):
    end = min(parse_date(c.data["end"]), until or today())
    if end < parse_date(c.data["start"]):
        return
    existing = set(s.scalars(select(Entry.key).where(Entry.space == sp.id, Entry.contract == c.id)).all())
    for row in calendar(c, end=str(end)):
        key = f"charge:{c.id}:{row['date']}" + (":final" if row["reason"].startswith("Завершающий") else "")
        if key not in existing and money(row["amount"]) > 0:
            post(
                s,
                sp,
                "charge",
                row["amount"],
                c.data["vehicle"],
                c.id,
                row["reason"],
                key,
                row["date"],
                direction=c.data["direction"],
            )


def book(s, sp, c, state="hold"):
    d = c.data
    s.query(Booking).filter(Booking.space == sp.id, Booking.state == "hold", Booking.expires < now()).update(
        {"state": "expired"}
    )
    b = Booking(
        space=sp.id,
        vehicle=d["vehicle"],
        contract=c.id,
        period=Range(datetime.fromisoformat(d["start_time"]), datetime.fromisoformat(d["end_time"]), "[)"),
        state=state,
        expires=now() + timedelta(minutes=30) if state == "hold" else None,
    )
    s.add(b)
    s.flush()
    return b


def own(s, sp, x):
    if not cansee(s, sp, x):
        fail("Недостаточно прав", 403)


def require_status(x, states):
    if x.data.get("status") not in states:
        fail("Действие недоступно в текущем состоянии", 409)


def command(s, sp, action, p, key):
    if sp.data.get("tg_user") and (not sp.data.get("pd_consent") or not sp.data.get("tg_role_chosen")):
        fail("Завершите онбординг в боте", 403)
    if action not in WRITE:
        fail("Неизвестная команда")
    if sp.role not in WRITE[action] and sp.role not in ("admin", "owner"):
        fail("Роль не может выполнить действие", 403)
    if not key or len(key) > 100:
        fail("Нужен ключ идемпотентности")
    targetless = {
        "demo_payment.create",
        "driver.inspection",
        "client.create",
        "contract.create",
        "ticket.create",
        "payment.create",
        "deposit.refund",
        "deposit.withhold",
        "period.close",
        "period.reopen",
        "owner.statement",
        "referral.create",
        "tariff.create",
    }
    if action not in targetless and not p.get("id"):
        fail("Укажите объект действия")
    s.execute(text("SELECT pg_advisory_xact_lock(hashtext(:id))"), {"id": sp.id})
    signature = hashlib.sha256(
        json.dumps({"a": action, "p": p}, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    old = s.scalar(select(Receipt).where(Receipt.space == sp.id, Receipt.key == key))
    if old:
        if old.result["signature"] != signature:
            fail("Ключ уже использован для другого действия", 409)
        return old.result["value"]
    x = get(s, sp, p["id"], lock=True) if p.get("id") and not action.startswith("entry.") else None
    if x:
        own(s, sp, x)
        expected = {
            "client": "client",
            "contract": "contract",
            "ticket": "ticket",
            "vehicle": "vehicle",
            "referral": "referral",
            "import": "import",
        }.get(action.split(".")[0])
        if expected and not action.endswith(".create") and x.kind != expected:
            fail("Команда не соответствует типу объекта")
        if "version" in p and p["version"] != x.version:
            fail("Запись изменена. Обновите карточку.", 409)
    result = {}
    title = ""
    if action.startswith("demo_payment."):
        from .miniapp import payment_command
        x, title = payment_command(s, sp, action, p, x)
    elif action == "driver.inspection":
        from .miniapp import inspection_command
        x, title = inspection_command(s, sp, p)
    elif action == "client.create":
        name = str(p.get("name", "")).strip()
        if not name or len(name) > 120:
            fail("Укажите имя / название до 120 символов")
        x = add(
            s,
            sp.id,
            "client",
            "CL-" + uid()[:6],
            {
                "name": name,
                "type": p.get("type", "person"),
                "phone": str(p.get("phone", ""))[:40],
                "status": "new",
                "documents": [],
                "age": int(p.get("age", 30)),
                "experience": int(p.get("experience", 5)),
                "representative": str(p.get("representative", ""))[:120],
            },
        )
        title = "Создана заявка клиента"
        if sp.role == "client":
            sp.data = {**sp.data, "client": x.id}
    elif action == "client.documents":
        if not x or x.kind != "client":
            fail("Нужна карточка клиента")
        documents = p.get("documents", [])
        if not isinstance(documents, list) or len(documents) > 15:
            fail("Некорректный список документов")
        attachments = p.get("document_files", x.data.get("document_files", []))
        if not isinstance(attachments, list) or len(attachments) > 6:
            fail("Некорректный комплект файлов")
        normalized = []
        for doc in attachments:
            if not isinstance(doc, dict) or doc.get("type") not in ("passport", "license"):
                fail("Укажите тип документа")
            f = get(s, sp, doc.get("file"), "file")
            if not file_access(s, sp, f) or f.data["ext"] not in (".png", ".jpg", ".jpeg", ".pdf"):
                fail("Недопустимый файл документа", 403)
            normalized.append({"type": doc["type"], "file": f.id, "name": f.data["name"]})
        names = [str(d)[:100] for d in documents]
        if "document_files" in p:
            names = sorted({"Паспорт" if d["type"] == "passport" else "Водительское удостоверение" for d in normalized})
        update(x, documents=names, document_files=normalized, status="review")
        title = "Документы переданы на проверку"
    elif action == "client.review":
        if x.kind != "client":
            fail("Нужен клиент")
        if not p.get("reason"):
            fail("Укажите основание решения")
        if p.get("approved") and len(x.data.get("documents", [])) < 2:
            fail("Недостаточно документов")
        update(
            x, status="approved" if p.get("approved") else "rejected", review_reason=str(p["reason"])[:500]
        )
        title = "Проверка клиента завершена"
    elif action == "contract.create":
        v = get(s, sp, p.get("vehicle"), "vehicle", True)
        client = get(s, sp, p.get("client") or sp.data.get(sp.role), "client")
        if sp.role not in STAFF and client.id != sp.data.get(sp.role):
            fail("Можно оформить только свой договор", 403)
        start = parse_date(p.get("start"))
        end = parse_date(p.get("end"))
        day_range(start, end)
        if end <= start or start < today():
            fail("Начало не раньше сегодня; окончание позже начала")
        if v.data["status"] != "ready":
            fail("Автомобиль не готов к выдаче", 409)
        direction = v.data["direction"]
        if sp.role == "client" and direction not in ("rental", "commercial"):
            fail("Клиенту доступен прокат", 403)
        if sp.role == "driver" and direction not in ("taxi", "buyout"):
            fail("Водителю доступны такси и выкуп", 403)
        quote = None
        if direction in ("rental", "commercial"):
            from .miniapp import rental_quote
            quote = rental_quote(s, sp, p)
            if p.get("quote_version") and p["quote_version"] != quote["version"]:
                fail("Цена изменилась. Обновите расчёт и подтвердите бронирование.", 409)
        schedule = p.get("schedule", "7/0")
        if schedule not in ("7/0", "6/1", "5/2"):
            fail("Некорректный график")
        rates = {"7/0": Decimal("1"), "6/1": Decimal("1.17"), "5/2": Decimal("1.4")}
        tariff = s.scalar(
            select(Item)
            .where(
                Item.space == sp.id,
                Item.kind == "tariff",
                Item.data["direction"].astext == direction,
                Item.data["effective"].astext <= str(start),
            )
            .order_by(Item.created.desc())
            .limit(1)
        )
        base = money(tariff.data["rate"]) if tariff and tariff.data.get("custom") else money(v.data["rate"])
        rate = (
            base * rates[schedule]
            if direction in ("taxi", "buyout")
            else base
            * (
                Decimal(".9")
                if (end - start).days >= 30
                else Decimal(".95") if (end - start).days >= 7 else Decimal("1")
            )
        )
        x = add(
            s,
            sp.id,
            "contract",
            "D-" + uid()[:6].upper(),
            {
                "vehicle": v.id,
                "client": client.id,
                "direction": direction,
                "status": "draft",
                "start": str(start),
                "end": str(end),
                "start_time": str(start) + "T10:00:00+03:00",
                "end_time": str(end) + "T10:00:00+03:00",
                "rate": str(money(rate)),
                "schedule": schedule,
                "free_first": direction == "taxi",
                "holidays": [],
                "deposit": "20000" if direction in ("rental", "commercial") else "0",
                "km_limit": 250,
                "extra_km": "30",
                "final_payment": str(money(p.get("final_payment", 150000))) if direction == "buyout" else "0",
                "tariff_version": 1,
                "addons": p.get("addons", []),
                "screened": client.data["status"] == "approved",
            },
        )
        if tariff:
            update(x, tariff_id=tariff.id, tariff_version=tariff.version)
        if direction == "buyout":
            update(
                x,
                terms_approved=False,
                proposal={
                    "rate": x.data["rate"],
                    "final_payment": x.data["final_payment"],
                    "start": x.data["start"],
                    "end": x.data["end"],
                    "schedule": schedule,
                    "created": now().isoformat(),
                },
            )
        if direction in ("rental", "commercial"):
            driver = str(p.get("additional_driver", "")).strip()[:120]
            delivery = bool(p.get("delivery"))
            collection = bool(p.get("collection"))
            daily = money(quote["addons_daily"])
            update(
                x,
                base_rate=quote["rental_rate"],
                rate=quote["rate"],
                additional_driver=driver,
                delivery=delivery,
                collection=collection,
                services_amount=quote["services_amount"],
                quote_total=quote["total"],
                quote_version=quote["version"],
                addons_daily=str(daily),
                addons_rule="Учебные услуги: дополнительный водитель 300 ₽/сутки, доставка и забор по 1500 ₽; топливо 50 ₽/процент недостачи",
            )
        book(s, sp, x)
        title = "Создан договор и резерв на 30 минут"
    elif action == "contract.approve_terms":
        require_status(x, ["draft"])
        if x.data["direction"] != "buyout":
            fail("Согласование предложения доступно для выкупа")
        rate = positive(p.get("rate", x.data["rate"]))
        final = money(p.get("final_payment", x.data["final_payment"]))
        if final < 0:
            fail("Финальный платёж не может быть отрицательным")
        update(
            x,
            rate=str(rate),
            final_payment=str(final),
            terms_approved=True,
            terms_reason=str(p.get("reason", "Индивидуальное предложение утверждено"))[:500],
            terms_approved_at=now().isoformat(),
        )
        title = "Условия предложения выкупа утверждены финансистом"
    elif action == "contract.confirm":
        require_status(x, ["draft"])
        client = get(s, sp, x.data["client"], "client")
        if client.data["status"] != "approved":
            fail("Клиент ещё не прошёл проверку")
        if x.data["direction"] == "buyout" and not x.data.get("terms_approved", True):
            fail("Сначала финансист должен утвердить предложение выкупа")
        if x.data["direction"] == "taxi" and (
            client.data.get("age", 0) < 21 or client.data.get("experience", 0) < 3
        ):
            fail("Для такси: возраст от 21 года, стаж от 3 лет")
        if client.data.get("type") == "company" and not client.data.get("representative"):
            fail("Укажите представителя организации")
        b = s.scalar(
            select(Booking).where(Booking.space == sp.id, Booking.contract == x.id, Booking.state == "hold")
        )
        if not b or b.expires < now():
            fail("Резерв истёк — создайте новый договор", 409)
        b.state = "confirmed"
        b.expires = None
        update(x, status="confirmed", screened=True)
        title = "Договор подтверждён"
    elif action == "contract.issue":
        require_status(x, ["confirmed"])
        v = get(s, sp, x.data["vehicle"], "vehicle", True)
        if v.data["status"] != "ready" or not v.data.get("inspection_ok"):
            fail("Сначала завершите осмотр и подготовку автомобиля")
        b = s.scalar(
            select(Booking).where(
                Booking.space == sp.id, Booking.contract == x.id, Booking.state == "confirmed"
            )
        )
        if not b:
            fail("Нет подтверждённой брони", 409)
        if parse_date(x.data["start"]) != today():
            fail("Выдача доступна в день начала договора")
        b.state = "active"
        update(x, status="active", initial_mileage=v.data["mileage"], issued_at=now().isoformat())
        bill(s, sp, x)
        update(x, initial_fuel=v.data.get("fuel", 75))
        if money(x.data.get("services_amount", 0)):
            post(
                s,
                sp,
                "charge",
                x.data["services_amount"],
                v.id,
                x.id,
                "Доставка / забор по условиям договора",
                component="services",
            )
        from .miniapp import balance
        deposit_due = max(Decimal(0), money(x.data["deposit"]) - balance(s, sp, x.id, ["deposit", "deposit_release"]))
        if deposit_due:
            post(
                s,
                sp,
                "deposit",
                deposit_due,
                v.id,
                x.id,
                "Получен возвратный залог",
                direction=x.data["direction"],
            )
        title = "Автомобиль выдан · акт готов"
    elif action == "contract.cancel":
        require_status(x, ["draft", "confirmed"])
        update(x, status="cancelled")
        from .miniapp import balance
        refundable = balance(s, sp, x.id, ["deposit", "deposit_release"])
        if refundable > 0:
            update(x, refund_requested=str(money(refundable)), refund_status="pending")
        s.query(Booking).filter(Booking.contract == x.id, Booking.space == sp.id).update(
            {"state": "cancelled"}
        )
        title = "Бронирование отменено"
    elif action == "contract.extend":
        require_status(x, ["active", "confirmed"])
        end = parse_date(p.get("end"))
        if end <= parse_date(x.data["end"]):
            fail("Новая дата должна быть позже текущей")
        day_range(x.data["start"], str(end))
        b = s.scalar(
            select(Booking).where(
                Booking.space == sp.id, Booking.contract == x.id, Booking.state.in_(["active", "confirmed"])
            )
        )
        if not b:
            fail("Бронирование не найдено")
        b.period = Range(b.period.lower, datetime.fromisoformat(str(end) + "T10:00:00+03:00"), "[)")
        s.flush()
        update(x, end=str(end), end_time=str(end) + "T10:00:00+03:00")
        title = "Аренда продлена"
    elif action == "contract.return":
        require_status(x, ["active"])
        if x.data["direction"] == "buyout":
            fail("Выкуп закрывается отдельным расчётом")
        v = get(s, sp, x.data["vehicle"], "vehicle", True)
        mileage = int(p.get("mileage", 0))
        fuel = int(p.get("fuel", 0))
        if mileage < x.data.get("initial_mileage", 0) or fuel not in range(101):
            fail("Проверьте пробег и топливо")
        returned = datetime.fromisoformat(p.get("returned_at", now().isoformat()))
        if returned.tzinfo is None:
            fail("Время возврата должно содержать часовой пояс")
        if returned > now() + timedelta(minutes=5):
            fail("Нельзя вернуть автомобиль в будущем")
        start = datetime.fromisoformat(x.data["start_time"])
        scheduled = datetime.fromisoformat(x.data["end_time"])
        if returned < start:
            fail("Возврат раньше выдачи")
        bill(s, sp, x, returned.astimezone(ZoneInfo("Europe/Moscow")).date())
        s.flush()
        days = max(1, math.ceil(((returned - start).total_seconds() - 7200) / 86400))
        excess = max(0, mileage - x.data.get("initial_mileage", mileage) - days * x.data["km_limit"])
        if x.data["direction"] in ("rental", "commercial"):
            charged = s.scalar(
                select(func.coalesce(func.sum(Entry.amount), 0)).where(
                    Entry.space == sp.id,
                    Entry.contract == x.id,
                    Entry.kind == "charge",
                    Entry.data["reason"].astext == "Аренда по договору",
                )
            )
            delta = money(days * money(x.data["rate"])) - charged
            if delta:
                post(
                    s,
                    sp,
                    "charge",
                    delta,
                    v.id,
                    x.id,
                    "Итоговый расчёт длительности проката",
                    key="return-rent:" + x.id,
                    days=days,
                )
        if excess:
            post(
                s,
                sp,
                "charge",
                excess * money(x.data["extra_km"]),
                v.id,
                x.id,
                "Перепробег",
                kilometers=excess,
            )
        if x.data["direction"] in ("rental", "commercial"):
            shortage = max(0, x.data.get("initial_fuel", fuel) - fuel)
            if shortage:
                post(
                    s,
                    sp,
                    "charge",
                    money(shortage * 50),
                    v.id,
                    x.id,
                    "Топливо: недостача при возврате",
                    percent=shortage,
                    component="fuel",
                )
        late = (returned - scheduled).total_seconds()
        late_days = math.ceil((late - 7200) / 86400) if late > 7200 else 0
        if late_days and x.data["direction"] == "taxi":
            post(
                s,
                sp,
                "charge",
                late_days * money(x.data["rate"]),
                v.id,
                x.id,
                "Поздний возврат",
                days=late_days,
            )
        photos = p.get("photos", [])
        for photo in photos:
            get(s, sp, photo, "file")
        act = add(
            s,
            sp.id,
            "inspection",
            "RETURN-" + uid()[:6],
            {
                "vehicle": v.id,
                "contract": x.id,
                "mileage": mileage,
                "fuel": fuel,
                "photos": photos,
                "damage": str(p.get("damage", "Зафиксировано при возврате"))[:1000],
                "date": returned.isoformat(),
                "type": "return",
            },
        )
        update(
            x,
            status="completed",
            returned_at=returned.isoformat(),
            return_mileage=mileage,
            excess_km=excess,
            late_days=late_days,
            return_inspection=act.id,
        )
        update(v, mileage=mileage, fuel=fuel, status="inspection", inspection_ok=False)
        s.query(Booking).filter(Booking.space == sp.id, Booking.contract == x.id).update(
            {"state": "completed"}
        )
        title = "Возврат оформлен · итоговый расчёт готов"
    elif action in ("contract.holiday", "contract.schedule", "contract.close_request"):
        require_status(x, ["active"])
        if action.endswith("holiday"):
            dates = [str(d) for d in day_range(p.get("start"), p.get("end"))]
            if dates[0] < str(today()) or dates[0] < x.data["start"] or dates[-1] > x.data["end"]:
                fail("Каникулы должны быть внутри будущего периода договора")
            update(x, holiday_request=dates, request_reason=str(p.get("reason", "Заявление клиента"))[:500])
        elif action.endswith("schedule"):
            if p.get("schedule") not in ("7/0", "6/1", "5/2"):
                fail("Укажите график")
            update(x, schedule_request=p["schedule"])
        else:
            update(x, close_requested=True)
        title = "Заявление передано финансисту"
    elif action == "contract.approve_holiday":
        dates = x.data.get("holiday_request", [])
        if not dates:
            fail("Нет заявления на каникулы")
        update(x, holidays=sorted(set(x.data.get("holidays", []) + dates)), holiday_request=[])
        for d in dates:
            existing = s.scalar(select(Entry).where(Entry.space == sp.id, Entry.key == f"charge:{x.id}:{d}"))
            if existing:
                post(
                    s,
                    sp,
                    "charge",
                    -existing.amount,
                    x.data["vehicle"],
                    x.id,
                    "Перерасчёт: согласованные каникулы",
                    key=f"holiday:{x.id}:{d}",
                    d=d,
                )
        title = "Каникулы согласованы"
    elif action == "contract.approve_schedule":
        requested = x.data.get("schedule_request")
        if not requested:
            fail("Нет заявления на изменение графика")
        update(
            x,
            schedule_history=[
                *x.data.get("schedule_history", []),
                {"schedule": x.data["schedule"], "until": str(today())},
            ],
            schedule=requested,
            schedule_request=None,
        )
        title = "Новый график действует со следующего дня"
    elif action == "contract.close_quote":
        if x.data["direction"] != "buyout":
            fail("Расчёт доступен для выкупа")
        require_status(x, ["active"])
        update(
            x,
            close_quote=str(positive(p.get("amount"))),
            close_quote_reason=str(p.get("reason", "Индивидуальный расчёт"))[:500],
        )
        title = "Расчёт досрочного выкупа утверждён"
    elif action == "contract.close":
        require_status(x, ["active"])
        if x.data["direction"] != "buyout" or not x.data.get("close_quote"):
            fail("Нужен утверждённый расчёт выкупа")
        if not p.get("confirmed"):
            fail("Подтвердите получение завершающего платежа")
        bill(s, sp, x)
        s.flush()
        due = s.scalar(
            select(func.coalesce(func.sum(Entry.amount), 0)).where(
                Entry.space == sp.id, Entry.contract == x.id, Entry.kind == "charge"
            )
        )
        paid = s.scalar(
            select(func.coalesce(func.sum(Entry.amount), 0)).where(
                Entry.space == sp.id, Entry.contract == x.id, Entry.kind == "payment"
            )
        )
        if due > paid:
            fail("Сначала погасите текущую задолженность: " + str(money(due - paid)) + " ₽")
        post(
            s,
            sp,
            "charge",
            x.data["close_quote"],
            x.data["vehicle"],
            x.id,
            "Досрочный выкуп по утверждённому расчёту",
        )
        post(s, sp, "payment", x.data["close_quote"], x.data["vehicle"], x.id, "Оплата досрочного выкупа")
        update(x, status="bought", closed_at=str(today()))
        s.query(Booking).filter(Booking.space == sp.id, Booking.contract == x.id).update(
            {"state": "completed"}
        )
        v = get(s, sp, x.data["vehicle"], "vehicle")
        update(v, status="sold")
        title = "Выкуп завершён · акт передачи готов"
    elif action == "vehicle.inspect":
        if x.kind != "vehicle":
            fail("Нужен автомобиль")
        if x.data["status"] == "sold":
            fail("Автомобиль передан в собственность")
        if s.scalar(
            select(Item.id).where(
                Item.space == sp.id,
                Item.kind == "ticket",
                Item.data["vehicle"].astext == x.id,
                Item.data["status"].astext == "repair",
            )
        ):
            fail("Сначала завершите ремонт")
        mileage = int(p.get("mileage", x.data["mileage"]))
        fuel = int(p.get("fuel", 75))
        if mileage < x.data["mileage"] or fuel not in range(101):
            fail("Проверьте пробег и топливо")
        photos = p.get("photos", [])
        for photo in photos:
            get(s, sp, photo, "file")
        inspection = add(
            s,
            sp.id,
            "inspection",
            "ACT-" + uid()[:6],
            {
                "vehicle": x.id,
                "mileage": mileage,
                "fuel": fuel,
                "damage": str(p.get("damage", "Нет новых повреждений"))[:1000],
                "equipment": str(p.get("equipment", "Ключи, СТС, аптечка"))[:500],
                "photos": photos,
                "date": now().isoformat(),
            },
        )
        quality = s.scalar(
            select(Item.id).where(
                Item.space == sp.id,
                Item.kind == "ticket",
                Item.data["vehicle"].astext == x.id,
                Item.data["status"].astext == "quality",
            )
        )
        update(
            x,
            mileage=mileage,
            fuel=fuel,
            inspection_ok=True,
            status="inspection" if quality else "ready",
            last_inspection=inspection.id,
        )
        title = "Контрольный осмотр завершён" if quality else "Осмотр завершён · автомобиль готов"
    elif action == "vehicle.transfer":
        if p.get("branch") not in {b["id"] for b in BRANCHES}:
            fail("Неизвестная площадка")
        if s.scalar(
            select(Booking.id).where(
                Booking.space == sp.id, Booking.vehicle == x.id, Booking.state == "active"
            )
        ):
            fail("Нельзя переместить выданный автомобиль")
        update(x, branch=p["branch"])
        title = "Автомобиль перемещён на другую площадку"
    elif action == "ticket.create":
        v = get(s, sp, p.get("vehicle"), "vehicle")
        own(s, sp, v)
        if sp.role == "client" and v.id not in allowed_vehicle_ids(s, sp):
            fail("Обращение доступно по своей аренде", 403)
        priority = p.get("priority", "technical")
        if priority not in ("urgent", "technical", "normal"):
            fail("Некорректный приоритет")
        photos = p.get("photos", [])
        from .miniapp import validate_photos
        validate_photos(s, sp, photos)
        for photo in photos:
            get(s, sp, photo, "file")
        active = s.scalar(
            select(Item).where(
                Item.space == sp.id,
                Item.kind == "contract",
                Item.data["vehicle"].astext == v.id,
                Item.data["status"].astext == "active",
            )
        )
        x = add(
            s,
            sp.id,
            "ticket",
            "SRV-" + uid()[:6].upper(),
            {
                "vehicle": v.id,
                "contract": active.id if active else None,
                "title": str(p.get("title", "Техническое обращение"))[:150],
                "description": str(p.get("description", ""))[:4000],
                "status": "new",
                "priority": priority,
                "assignee": "Технический отдел",
                "estimate": "0",
                "payer": "owner" if v.data.get("investor") else "company",
                "due": sla_due(priority).isoformat(),
                "opened": now().isoformat(),
                "photos": photos,
                "location": str(p.get("location", ""))[:500],
                "subtype": "accident" if p.get("subtype") == "accident" else "request",
            },
        )
        title = "Обращение зарегистрировано"
    elif action == "ticket.estimate":
        require_status(x, ["new", "estimate"])
        payer = p.get("payer", "company")
        if payer not in ("company", "driver", "owner", "insurance"):
            fail("Неизвестный плательщик")
        v = get(s, sp, x.data["vehicle"], "vehicle")
        if payer == "owner" and not v.data.get("investor"):
            fail("У автомобиля нет стороннего владельца")
        update(
            x,
            estimate=str(positive(p.get("amount"))),
            payer=payer,
            status="estimate",
            work=str(p.get("work", "Ремонт согласно осмотру"))[:2000],
        )
        title = "Смета направлена на согласование"
    elif action == "ticket.schedule":
        require_status(x, ["new", "estimate", "approved"])
        day = parse_date(p.get("day"))
        slot = str(p.get("slot", "10:00"))
        if day < today() or slot not in ("09:00", "11:00", "13:00", "15:00", "17:00"):
            fail("Выберите будущий день и сервисный интервал")
        scheduled = str(day) + "T" + slot + ":00+03:00"
        if s.scalar(
            select(Item.id).where(
                Item.space == sp.id,
                Item.kind == "ticket",
                Item.id != x.id,
                Item.data["scheduled_at"].astext == scheduled,
                Item.data["status"].astext != "closed",
            )
        ):
            fail("Сервисный пост занят в выбранное время. Выберите другой интервал.", 409)
        update(x, scheduled_at=scheduled, answered_at=now().isoformat(), assignee="Технический отдел")
        title = "Запись на сервис подтверждена"
    elif action == "ticket.substitute":
        require_status(x, ["approved", "repair", "quality"])
        if not x.data.get("contract"):
            fail("Подмена оформляется для действующего договора")
        source = get(s, sp, x.data["contract"], "contract")
        if source.data["status"] != "active":
            fail("Исходный договор уже завершён")
        if x.data.get("substitute_contract"):
            fail("Подменный договор уже создан")
        v = get(s, sp, p.get("vehicle"), "vehicle")
        if v.id == x.data["vehicle"] or v.data["direction"] == "buyout":
            fail("Выберите другой автомобиль такси или проката")
        child = command(
            s,
            sp,
            "contract.create",
            {
                "vehicle": v.id,
                "client": source.data["client"],
                "start": str(today()),
                "end": str(parse_date(p.get("end"))),
                "schedule": "7/0",
            },
            hashlib.sha256((key + ":substitute").encode()).hexdigest(),
        )
        child_contract = get(s, sp, child["id"], "contract")
        update(child_contract, substitution_for=source.id)
        update(x, substitute_contract=child["id"])
        title = "Подменный автомобиль зарезервирован; подтвердите договор и выдачу. Освобождение исходного договора согласуется отдельно."
    elif action == "ticket.approve":
        require_status(x, ["estimate"])
        if sp.role == "investor" and x.data["payer"] != "owner":
            fail("Владелец согласует только свои расходы", 403)
        if money(x.data.get("estimate", 0)) <= 0:
            fail("Укажите стоимость работ")
        update(x, status="approved", approved_by=sp.role)
        title = "Смета согласована"
    elif action == "ticket.start":
        require_status(x, ["approved"])
        v = get(s, sp, x.data["vehicle"], "vehicle")
        update(v, status="repair", inspection_ok=False, down_since=now().isoformat())
        update(x, status="repair", repair_started=now().isoformat())
        title = "Автомобиль принят в ремонт"
    elif action == "ticket.complete":
        require_status(x, ["repair"])
        v = get(s, sp, x.data["vehicle"], "vehicle")
        actual = positive(p.get("amount", x.data["estimate"]))
        if actual > money(x.data["estimate"]):
            fail("Превышение сметы требует нового согласования")
        post(
            s,
            sp,
            "expense",
            actual,
            v.id,
            x.data.get("contract"),
            "Ремонт: " + x.data["title"],
            payer=x.data["payer"],
            ticket=x.id,
        )
        if x.data["payer"] == "driver" and x.data.get("contract"):
            post(s, sp, "charge", actual, v.id, x.data["contract"], "Ремонт за счёт водителя", ticket=x.id)
        if x.data["payer"] == "insurance":
            post(
                s,
                sp,
                "receivable",
                actual,
                v.id,
                x.data.get("contract"),
                "Ожидаемое страховое возмещение",
                ticket=x.id,
            )
        update(x, status="quality", actual=str(actual))
        update(v, status="inspection")
        title = "Ремонт завершён · расходы проведены"
    elif action == "ticket.release":
        require_status(x, ["quality"])
        v = get(s, sp, x.data["vehicle"], "vehicle")
        if not v.data.get("inspection_ok"):
            fail("Сначала выполните контрольный осмотр автомобиля")
        elapsed = max(
            0,
            int(
                (now() - datetime.fromisoformat(v.data.get("down_since", now().isoformat()))).total_seconds()
                / 3600
            ),
        )
        update(x, status="closed", downtime_hours=elapsed, closed_at=now().isoformat())
        update(v, status="ready")
        title = "Автомобиль возвращён в эксплуатацию"
    elif action == "payment.create":
        c = get(s, sp, p.get("contract"), "contract")
        post(
            s,
            sp,
            "payment",
            positive(p.get("amount")),
            c.data["vehicle"],
            c.id,
            "Поступление по договору",
            direction=c.data["direction"],
        )
        x = c
        title = "Оплата зачислена"
    elif action == "entry.reverse":
        e = s.scalar(select(Entry).where(Entry.space == sp.id, Entry.id == p.get("id")))
        if not e or not p.get("reason"):
            fail("Нужны операция и основание")
        if s.scalar(select(Entry.id).where(Entry.space == sp.id, Entry.key == "reverse:" + e.id)):
            fail("Операция уже сторнирована")
        post(
            s,
            sp,
            e.kind,
            -e.amount,
            e.vehicle,
            e.contract,
            "Сторно: " + str(p["reason"]),
            key="reverse:" + e.id,
            original=e.id,
        )
        title = "Создано сторно операции"
    elif action in ("deposit.refund", "deposit.withhold"):
        c = get(s, sp, p.get("contract"), "contract")
        balance = s.scalar(
            select(func.coalesce(func.sum(Entry.amount), 0)).where(
                Entry.space == sp.id, Entry.contract == c.id, Entry.kind.in_(["deposit", "deposit_release"])
            )
        )
        amount = positive(p.get("amount"))
        if amount > balance:
            fail("Сумма превышает остаток залога")
        if not p.get("reason"):
            fail("Укажите основание")
        post(s, sp, "deposit_release", -amount, c.data["vehicle"], c.id, p["reason"])
        if action.endswith("withhold"):
            post(s, sp, "charge", amount, c.data["vehicle"], c.id, "Удержание: " + p["reason"])
            post(s, sp, "payment", amount, c.data["vehicle"], c.id, "Зачёт из залога")
        else:
            post(s, sp, "cash_refund", amount, c.data["vehicle"], c.id, "Возврат залога")
        if c.data.get("refund_status") == "pending":
            update(c, refund_requested=str(money(balance - amount)), refund_status="completed" if balance == amount else "pending")
        x = c
        title = "Залог обработан"
    elif action.startswith("period."):
        month = str(p.get("month", ""))
        parse_date(month + "-01")
        closed = set(sp.data.get("closed_months", []))
        if action.endswith("close"):
            closed.add(month)
        else:
            closed.discard(month)
        sp.data = {**sp.data, "closed_months": sorted(closed)}
        title = "Период закрыт" if action.endswith("close") else "Период переоткрыт"
    elif action == "owner.statement":
        inv = get(s, sp, p.get("investor"), "investor")
        month = str(p.get("month", str(today())[:7]))
        parse_date(month + "-01")
        code = inv.code + ":" + month
        old = s.scalar(select(Item).where(Item.space == sp.id, Item.kind == "statement", Item.code == code))
        if old:
            fail("Отчёт за этот месяц уже сформирован")
        vs = s.scalars(
            select(Item).where(
                Item.space == sp.id, Item.kind == "vehicle", Item.data["investor"].astext == inv.id
            )
        ).all()
        lines = []
        for v in vs:
            es = s.scalars(
                select(Entry).where(Entry.space == sp.id, Entry.vehicle == v.id, Entry.date.like(month + "%"))
            ).all()
            income = sum((e.amount for e in es if e.kind == "payment"), Decimal(0))
            cost = sum(
                (e.amount for e in es if e.kind == "expense" and e.data.get("payer") in ("owner", "company")),
                Decimal(0),
            )
            payout = money(income * Decimal(inv.data["share"]) - cost * Decimal(inv.data["expense_share"]))
            lines.append(
                {
                    "vehicle": v.id,
                    "model": v.data["model"],
                    "income": str(income),
                    "expenses": str(cost),
                    "amount": str(payout),
                }
            )
        x = add(
            s,
            sp.id,
            "statement",
            code,
            {
                "investor": inv.id,
                "month": month,
                "status": "draft",
                "lines": lines,
                "amount": str(sum((money(l["amount"]) for l in lines), Decimal(0))),
                "basis": "Полученные арендные платежи; залоги исключены",
                "share": inv.data["share"],
                "expense_share": inv.data["expense_share"],
            },
        )
        title = "Отчёт владельца сформирован"
    elif action == "owner.approve":
        if x.kind != "statement":
            fail("Нужен отчёт владельца")
        require_status(x, ["draft"])
        update(x, status="approved")
        title = "Отчёт владельца утверждён"
    elif action == "owner.pay":
        if x.kind != "statement":
            fail("Нужен отчёт владельца")
        require_status(x, ["approved"])
        if money(x.data["amount"]) <= 0:
            fail("Нет положительной суммы к выплате")
        positive_lines = [line for line in x.data["lines"] if money(line["amount"]) > 0]
        base = sum((money(line["amount"]) for line in positive_lines), Decimal(0))
        remaining = money(x.data["amount"])
        breakdown = []
        for i, line in enumerate(positive_lines):
            amount = (
                remaining
                if i == len(positive_lines) - 1
                else money(money(x.data["amount"]) * money(line["amount"]) / base)
            )
            remaining -= amount
            post(
                s,
                sp,
                "owner_payout",
                amount,
                line["vehicle"],
                reason="Выплата владельцу " + x.data["month"],
                statement=x.id,
            )
            breakdown.append({"vehicle": line["vehicle"], "amount": str(amount)})
        update(x, status="paid", payment_breakdown=breakdown)
        title = "Выплата владельцу зарегистрирована"
    elif action == "referral.create":
        client = get(s, sp, p.get("client") or sp.data.get("driver"), "client")
        invited = get(s, sp, p.get("invited"), "client")
        if sp.role == "driver" and client.id != sp.data.get("driver"):
            fail("Можно пригласить только от своего имени", 403)
        if client.id == invited.id:
            fail("Нельзя пригласить себя")
        if s.scalar(
            select(Item.id).where(
                Item.space == sp.id, Item.kind == "referral", Item.data["invited"].astext == invited.id
            )
        ):
            fail("Участник уже приглашён")
        x = add(
            s,
            sp.id,
            "referral",
            "REF-" + uid()[:6],
            {"client": client.id, "invited": invited.id, "status": "pending", "amount": "0"},
        )
        title = "Приглашение зарегистрировано"
    elif action == "referral.approve":
        require_status(x, ["pending"])
        c = get(s, sp, p.get("contract"), "contract")
        if c.data["client"] != x.data["invited"] or c.data["status"] != "active":
            fail("Нужен активный договор приглашённого участника")
        amount = 15000 if c.data["direction"] == "buyout" else 5000
        if s.scalar(select(Entry.id).where(Entry.space == sp.id, Entry.key == "referral:" + c.id)):
            fail("Бонус по договору уже начислен")
        post(
            s,
            sp,
            "bonus",
            amount,
            c.data["vehicle"],
            c.id,
            "Реферальное вознаграждение",
            key="referral:" + c.id,
        )
        update(x, status="approved", amount=str(amount), contract=c.id)
        title = "Реферальный бонус начислен"
    elif action == "tariff.create":
        rate = positive(p.get("rate"))
        direction = p.get("direction", "taxi")
        if direction not in ("taxi", "rental", "commercial", "buyout"):
            fail("Неизвестное направление")
        x = add(
            s,
            sp.id,
            "tariff",
            "TAR-" + uid()[:6],
            {
                "name": str(p.get("name", "Новый тариф"))[:100],
                "direction": direction,
                "rate": str(rate),
                "version": 1,
                "status": "active",
                "custom": True,
                "effective": str(parse_date(p.get("effective", str(today())))),
            },
        )
        title = "Создана новая версия тарифа"
    elif action == "import.commit":
        if x.kind != "import":
            fail("Нужен предварительный импорт")
        require_status(x, ["preview"])
        posted = 0
        unmatched = []
        for row in x.data["rows"]:
            if row.get("error"):
                unmatched.append(row)
                continue
            c = s.scalar(
                select(Item).where(
                    Item.space == sp.id, Item.kind == "contract", Item.code == row.get("contract")
                )
            )
            if not c:
                unmatched.append({**row, "error": "Договор не найден"})
                continue
            bankkey = "bank:" + row["reference"]
            if s.scalar(select(Entry.id).where(Entry.space == sp.id, Entry.key == bankkey)):
                continue
            post(
                s,
                sp,
                "payment",
                positive(row["amount"]),
                c.data["vehicle"],
                c.id,
                "Банковская выписка",
                key=bankkey,
                d=row["date"],
                source="file",
            )
            posted += 1
        update(x, status="review" if unmatched else "completed", posted=posted, unmatched=unmatched)
        title = f"Выписка обработана: {posted} платежей"
    elif action == "import.resolve":
        if x.kind != "import":
            fail("Нужен импорт")
        rows = list(x.data.get("unmatched", []))
        index = int(p.get("index", -1))
        if index not in range(len(rows)):
            fail("Строка не найдена")
        row = rows.pop(index)
        c = get(s, sp, p.get("contract"), "contract")
        bankkey = "bank:" + row["reference"]
        if s.scalar(select(Entry.id).where(Entry.space == sp.id, Entry.key == bankkey)):
            fail("Платёж уже зачислен")
        post(
            s,
            sp,
            "payment",
            positive(row["amount"]),
            c.data["vehicle"],
            c.id,
            "Ручная сверка выписки",
            key=bankkey,
            d=row["date"],
        )
        update(x, unmatched=rows, status="review" if rows else "completed")
        title = "Платёж сопоставлен с договором"
    if x:
        result = serialize(x)
    audit(
        s,
        sp,
        title or action,
        x.id if x else None,
        action=action,
        via="telegram" if key.startswith("tg:") else "web",
    )
    s.add(Receipt(space=sp.id, key=key, result={"signature": signature, "value": result}))
    s.flush()
    return result
