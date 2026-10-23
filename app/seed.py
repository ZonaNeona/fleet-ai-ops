import secrets, random
from datetime import timedelta, datetime
from zoneinfo import ZoneInfo
from decimal import Decimal
from sqlalchemy import select, func
from psycopg.types.range import Range
from .db import Space, Item, Entry, Booking, Event, uid, now

ROLES = {
    "owner": "Собственник бизнеса",
    "manager": "Менеджер",
    "service": "Сервис",
    "finance": "Финансист",
    "screening": "Проверка документов",
    "driver": "Водитель",
    "client": "Клиент проката",
    "investor": "Владелец автомобиля",
    "admin": "Администратор",
}
BRANCHES = [
    {
        "id": "vernadskogo",
        "name": "Вернадского",
        "address": "у м. Проспект Вернадского (учебный адрес)",
        "hours": "09:00–21:00 ежедневно",
        "x": 31,
        "y": 74,
    },
    {
        "id": "mitino",
        "name": "Митино",
        "address": "у м. Митино (учебный адрес)",
        "hours": "10:00–19:00 пн–пт",
        "x": 23,
        "y": 20,
    },
    {
        "id": "kuntsevo",
        "name": "Кунцево",
        "address": "у м. Кунцевская (учебный адрес)",
        "hours": "10:00–19:00 пн–пт",
        "x": 18,
        "y": 49,
    },
]
SOURCES = [
    {
        "title": "О парке · учебный",
        "url": None,
        "text": "Учебный таксопарк: такси, прокат, коммерческий транспорт и аренда с выкупом. Три площадки в Москве.",
        "version": "1.0",
    },
    {
        "title": "Тарифы · учебные",
        "url": None,
        "text": "Москвич 3: 7/0 — 2000 ₽; 6/1 — 2340 ₽; 5/2 — 2800 ₽. Ставка фиксируется договором.",
        "version": "1.0",
    },
    {
        "title": "Оформление водителя · учебное",
        "url": None,
        "text": "От 21 года, стаж от 3 лет. Паспорт, ВУ, КИС АРТ, справка о несудимости, самозанятость или ИП. Решение принимает сотрудник.",
        "version": "1.0",
    },
    {
        "title": "Выкуп · учебный",
        "url": None,
        "text": "Индивидуальный договор, финальный выкупной платёж, каникулы, досрочное закрытие. Сроки — по утверждённому графику.",
        "version": "1.0",
    },
    {
        "title": "Условия проката · учебные",
        "url": None,
        "text": "Сутки — 24 часа. При превышении более двух часов — следующие сутки. Залог не является выручкой.",
        "version": "1.0",
    },
    {
        "title": "Автомобили владельцев · учебное",
        "url": None,
        "text": "Владельцу 70% дохода и все расходы либо 50% дохода и 50% расходов. Ремонт согласуется с владельцем.",
        "version": "1.0",
    },
    {
        "title": "Реферальная программа · учебная",
        "url": None,
        "text": "Бонусы 5000 ₽ за аренду и 15000 ₽ за выкуп. Начисляются после активации договора и подтверждения финансиста.",
        "version": "1.0",
    },
    {
        "title": "Регламент ремонта · учебный",
        "url": None,
        "text": "Зафиксировать обращение, осмотр, смету, плательщика. После согласования провести ремонт и контроль готовности. Списание и остановка начислений требуют подтверждения. Аварийное обращение: реакция 15 минут; техническое: 2 часа.",
        "version": "1.0",
    },
    {
        "title": "Регламент расчётов · учебный",
        "url": None,
        "text": "База выплат владельцу — полученная аренда за вычетом возвратов, без залогов. Расходы распределяются по договору. Общие расходы — по доступным автомобиледням. Финансовые исправления выполняются сторно.",
        "version": "1.0",
    },
]


def _car(model, slug, cls, rate, lease):
    return {"model": model, "slug": slug, "class": cls, "rate": rate, "lease": lease}


FLEET = {
    c["slug"]: c
    for c in [
        _car("Skoda Rapid", "skoda-rapid", "Эконом", 1500, 21000),
        _car("Volkswagen Polo", "vw-polo", "Эконом", 1900, 23000),
        _car("Москвич 3", "moskvich-3", "Комфорт", 2200, 25000),
        _car("Geely Emgrand", "geely-emgrand", "Комфорт", 2200, 25000),
        _car("Chery Tiggo 4 Pro", "chery-tiggo-4", "Комфорт", 2200, 26000),
        _car("Belgee X50", "belgee-x50", "Комфорт", 2400, 27000),
        _car("Haval F7", "haval-f7", "Комфорт+", 2800, 31000),
        _car("Hyundai Sonata", "hyundai-sonata", "Комфорт+", 2800, 33000),
        _car("Exeed LX", "exeed-lx", "Комфорт+", 2800, 32000),
        _car("Haval Jolion", "haval-jolion", "Комфорт", 3300, 34000),
        _car("Geely Preface", "geely-preface", "Бизнес", 4800, 48000),
        _car("Hongqi H5", "hongqi-h5", "Бизнес", 5300, 55000),
        _car("Mercedes-Benz E 200", "mercedes-e", "Премиум", 14000, 165000),
        _car("BMW XM", "bmw-xm", "Премиум", 37000, 430000),
        _car("Zeekr 9X", "zeekr-9x", "Премиум", 45000, 470000),
        _car("Lada Largus", "lada-largus", "Грузовой", 2000, 22000),
        _car("Sollers Atlant", "sollers-atlant", "Грузовой", 4200, 46000),
        _car("Sollers Argo", "sollers-argo", "Грузовой", 5500, 52000),
        _car("ГАЗель Next", "gazelle-next", "Грузовой", 4800, 50000),
    ]
}
REPAIRS = [
    ("Кузовной ремонт после ДТП", 18000, 65000),
    ("Замена тормозных колодок и дисков", 7000, 16000),
    ("Ремонт подвески", 9000, 28000),
    ("Сезонная замена шин", 4000, 9000),
    ("Диагностика и ремонт электрики", 5000, 21000),
]
OVERHEAD = [
    ("payroll", "ФОТ: менеджеры, механики, финансы", 640000),
    ("sites", "Аренда трёх площадок", 255000),
    ("it", "IT, связь, телефония, сервисы", 68000),
]


def add(s, space, kind, code, data):
    x = Item(id=uid(), space=space, kind=kind, code=code, data=data, version=1)
    s.add(x)
    return x


def create_space(s, count=160):
    rng = random.Random(42)
    space = Space(id=uid(), token=secrets.token_hex(32), data={})
    s.add(space)
    s.flush()
    today = now().astimezone(ZoneInfo("Europe/Moscow")).date()
    customers = []
    names = [
        "Александр Соколов",
        "Михаил Орлов",
        "Дмитрий Волков",
        "Артём Лебедев",
        "Иван Морозов",
        "Сергей Козлов",
        "Андрей Новиков",
        "Елена Попова",
        "Мария Васильева",
        "Олег Смирнов",
    ]
    for i in range(48):
        name = (
            names[i % 10] + f" · {i+1:02}"
            if i < 40
            else [
                "ООО «Демо Логистика»",
                "ООО «Север Проект»",
                "ООО «Меридиан»",
                "ООО «Новый маршрут»",
            ][i % 4]
            + f" {i}"
        )
        customers.append(
            add(
                s,
                space.id,
                "client",
                f"CL-{i+1:03}",
                {
                    "name": name,
                    "type": "person" if i < 40 else "company",
                    "phone": f"+7 (000) 000-{i+1:04}",
                    "status": "approved" if i < 42 else "new",
                    "documents": (
                        ["Паспорт", "ВУ", "КИС АРТ", "Справка", "Самозанятость"]
                        if i < 42
                        else []
                    ),
                    "age": 28 + i % 20,
                    "experience": 4 + i % 12,
                    "representative": "Учебный представитель" if i >= 40 else "",
                    "note": "Вымышленный участник демонстрационного парка",
                },
            )
        )
    investor = add(
        s,
        space.id,
        "investor",
        "INV-01",
        {"name": "Алексей Воронов", "share": "0.70", "expense_share": "1.00"},
    )
    second = add(
        s,
        space.id,
        "investor",
        "INV-02",
        {"name": "Ирина Миронова", "share": "0.50", "expense_share": "0.50"},
    )
    # Модели — настоящие, суточные ставки — условные (учебные);
    # «lease» — ежемесячный платёж за автомобиль (лизинг/амортизация), учебная оценка.
    models = {
        "taxi": [
            FLEET["skoda-rapid"],
            FLEET["vw-polo"],
            FLEET["moskvich-3"],
            FLEET["geely-emgrand"],
            FLEET["chery-tiggo-4"],
            FLEET["belgee-x50"],
            FLEET["haval-f7"],
            FLEET["hyundai-sonata"],
            FLEET["exeed-lx"],
            FLEET["moskvich-3"],
        ],
        # премиум в прокате — штучно, основная масса — комфорт и бизнес
        "rental": [FLEET["haval-jolion"], FLEET["geely-preface"], FLEET["hongqi-h5"]]
        * 7
        + [
            FLEET["mercedes-e"],
            FLEET["mercedes-e"],
            FLEET["bmw-xm"],
            FLEET["zeekr-9x"],
        ],
        "commercial": [
            FLEET["lada-largus"],
            FLEET["sollers-atlant"],
            FLEET["sollers-argo"],
            FLEET["gazelle-next"],
        ],
        "buyout": [
            FLEET["moskvich-3"],
            FLEET["belgee-x50"],
            FLEET["geely-emgrand"],
            FLEET["haval-f7"],
        ],
    }
    vehicles = []
    contracts = []
    entry_batch = []
    for i in range(count):
        kind = (
            "taxi"
            if i % 160 < 60
            else (
                "rental"
                if i % 160 < 110
                else "commercial" if i % 160 < 130 else "buyout"
            )
        )
        car = models[kind][i % len(models[kind])]
        model = car["model"]
        rate = car["rate"] + (200 if kind == "buyout" else 0)
        state = "repair" if i % 19 == 7 else "inspection" if i % 23 == 9 else "ready"
        v = add(
            s,
            space.id,
            "vehicle",
            f"TP-{i+1:04}",
            {
                "model": model,
                "plate": f"ДЕМО {i+1:04}",
                "year": 2023 + i % 3,
                "direction": kind,
                "branch": BRANCHES[i % 3]["id"],
                "status": state,
                "rate": str(rate),
                "mileage": 15000 + i * 739,
                "next_to": 20000 + (i * 739 // 10000) * 10000,
                "document_until": str(today + timedelta(days=14 + i % 130)),
                "investor": (
                    investor.id
                    if i % 160 in range(60, 72)
                    else second.id if i % 160 in range(72, 84) else None
                ),
                "fuel": 75,
                "class": car["class"],
                "inspection_ok": state == "ready",
                "image": f"/cars/{car['slug']}.webp",
                "thumb": f"/cars/{car['slug']}-sm.webp",
            },
        )
        vehicles.append(v)
        start = today - timedelta(days=60 + i % 28)
        end = today + timedelta(
            days=365 if kind == "buyout" else 30 if kind == "taxi" else 4 + i % 10
        )
        if i % 5 == 0:
            end = today - timedelta(days=7)
        c = add(
            s,
            space.id,
            "contract",
            f"D-{1001+i}",
            {
                "vehicle": v.id,
                "client": customers[
                    i % 40 if kind in ("taxi", "buyout") else 40 + i % 8
                ].id,
                "direction": kind,
                "status": "active" if i % 5 != 0 else "completed",
                "start": str(start),
                "end": str(end),
                "rate": str(rate),
                "schedule": (
                    "7/0"
                    if kind in ("rental", "commercial") or i % 3 == 0
                    else "6/1" if i % 3 == 1 else "5/2"
                ),
                "free_first": True,
                "holidays": [],
                "deposit": str(
                    (100000 if car["class"] == "Премиум" else 20000)
                    if kind in ("rental", "commercial")
                    else 0
                ),
                "km_limit": 250,
                "extra_km": "30",
                "final_payment": "150000" if kind == "buyout" else "0",
                "tariff_version": 1,
                "initial_mileage": v.data["mileage"] - 500,
                "start_time": str(start) + "T10:00:00+03:00",
                "end_time": str(end) + "T10:00:00+03:00",
                "addons": [],
                "screened": True,
                "overdue_demo": False,
            },
        )
        contracts.append(c)
        if c.data["status"] == "active":
            s.add(
                Booking(
                    space=space.id,
                    vehicle=v.id,
                    contract=c.id,
                    period=Range(
                        datetime.fromisoformat(c.data["start_time"]),
                        datetime.fromisoformat(c.data["end_time"]),
                        "[)",
                    ),
                    state="active",
                )
            )
        # Historical settled contracts allow 90-day history without claiming future payments.
        for day in range(90):
            d = today - timedelta(days=89 - day)
            if (d - start).days < 0:
                continue
            if c.data["status"] == "completed" and d > today - timedelta(days=8):
                continue
            off = (c.data["schedule"] == "6/1" and d.weekday() == 6) or (
                c.data["schedule"] == "5/2" and d.weekday() >= 5
            )
            amount = Decimal(0 if off or (d == start and kind == "taxi") else rate)
            if amount:
                entry_batch.append(
                    dict(
                        space=space.id,
                        vehicle=v.id,
                        contract=c.id,
                        kind="charge",
                        amount=amount,
                        date=str(d),
                        key=f"charge:{c.id}:{d}",
                        data={
                            "reason": "Аренда по договору",
                            "source": "demo",
                            "direction": kind,
                        },
                    )
                )
                # Two unpaid recent days make the default driver's payment scenario usable.
                paid = amount if (day < 86 or i % 7 != 0) and not (i == 1 and day >= 88) else Decimal(0)
                if paid:
                    entry_batch.append(
                        dict(
                            space=space.id,
                            vehicle=v.id,
                            contract=c.id,
                            kind="payment",
                            amount=paid,
                            date=str(d),
                            key=f"seedpay:{c.id}:{d}",
                            data={
                                "reason": "Оплата аренды",
                                "source": "demo",
                                "direction": kind,
                            },
                        )
                    )
        # Расходы по автомобилю за 90 дней: ежемесячные платежи + ТО + случайные ремонты.
        premium = car["class"] == "Премиум"
        for month in range(3):
            d = today - timedelta(days=5 + (i % 20) + 30 * month)
            costs = [
                ("lease", "Лизинговый платёж", car["lease"]),
                ("insurance", "ОСАГО и КАСКО", round(car["lease"] * 0.17 / 100) * 100),
                (
                    "maintenance",
                    "ТО и расходники",
                    (9000 if premium else 3500) + i % 5 * 400,
                ),
                (
                    "wash",
                    "Мойка и химчистка",
                    4500 if premium else 1800 if kind == "taxi" else 2400,
                ),
            ]
            if rng.random() < 0.28:
                title, low, high = rng.choice(REPAIRS)
                costs.append(
                    (
                        "repair",
                        title,
                        rng.randrange(low, high, 500) * (3 if premium else 1),
                    )
                )
            for code, reason, amount in costs:
                entry_batch.append(
                    dict(
                        space=space.id,
                        vehicle=v.id,
                        contract=c.id,
                        kind="expense",
                        amount=Decimal(amount),
                        date=str(d),
                        key=f"{code}:{v.id}:{month}",
                        data={
                            "reason": reason,
                            "payer": "company",
                            "direction": kind,
                            "category": code,
                        },
                    )
                )
        if kind in ("rental", "commercial") and c.data["status"] == "active":
            s.add(
                Entry(
                    space=space.id,
                    vehicle=v.id,
                    contract=c.id,
                    kind="deposit",
                    amount=Decimal(c.data["deposit"]),
                    date=str(start),
                    key=f"deposit:{c.id}",
                    data={"reason": "Возвратный залог", "direction": kind},
                )
            )
        c.data = {**c.data, "free_first": kind == "taxi"}
        if i % 25 == 24 or i == count - 1:
            s.flush()
            if entry_batch:
                s.execute(Entry.__table__.insert(), entry_batch)
                entry_batch = []
    # Three genuine demo workflow starting points.
    for j, idx in enumerate([7, 26, 45, 64, 83, 102, 121, 140]):
        if idx >= len(vehicles):
            continue
        v = vehicles[idx]
        if j % 4 == 3:
            v.data = {
                **v.data,
                "down_since": (now() - timedelta(days=9 + j)).isoformat(),
            }
        add(
            s,
            space.id,
            "ticket",
            f"SRV-{201+j}",
            {
                "vehicle": v.id,
                "contract": contracts[idx].id,
                "title": [
                    "Не запускается двигатель",
                    "Плановое ТО · замена масла",
                    "Повреждение переднего бампера",
                    "Диагностика коробки",
                ][j % 4],
                "description": "Учебное обращение. Требуется осмотр и согласование работ.",
                "status": ["new", "estimate", "approved", "repair"][j % 4],
                "priority": "urgent" if j == 0 else "technical",
                "assignee": "Технический отдел",
                "estimate": str(8400 + j * 2300),
                "payer": "owner" if v.data["investor"] else "company",
                "due": (now() + timedelta(minutes=15 if j == 0 else 120)).isoformat(),
                "opened": now().isoformat(),
                "repair_started": (
                    (now() - timedelta(days=9 + j)).isoformat() if j % 4 == 3 else None
                ),
                "photos": [],
            },
        )
    for i in range(4):
        add(
            s,
            space.id,
            "tariff",
            f"TAR-{i}",
            {
                "name": [
                    "Такси · базовый",
                    "Прокат · стандарт",
                    "Коммерческий · стандарт",
                    "Выкуп · индивидуальный",
                ][i],
                "direction": ["taxi", "rental", "commercial", "buyout"][i],
                "version": 1,
                "rate": str([2200, 4800, 4200, 2600][i]),
                "status": "active",
                "effective": str(today),
                "schedule": "7/0",
            },
        )
    for i, title in enumerate(
        ["Ремонт: кто оплачивает?", "Как начисляется аренда?", "Документы водителя"]
    ):
        add(
            s,
            space.id,
            "knowledge",
            f"KB-{i}",
            {
                "title": title,
                "text": SOURCES[[7, 8, 2][i]]["text"],
                "version": "1.0",
                "roles": [
                    "owner",
                    "manager",
                    "service",
                    "finance",
                    "driver",
                    "client",
                    "investor",
                    "admin",
                    "screening",
                ],
            },
        )
    add(
        s,
        space.id,
        "referral",
        "REF-01",
        {
            "client": customers[0].id,
            "invited": customers[43].id,
            "status": "pending",
            "amount": "5000",
            "contract": None,
        },
    )
    # Общие расходы группы помесячно: распределяются по автомобиледням в отчётах
    months = [today.replace(day=1)]
    for _ in range(2):
        months.append((months[-1] - timedelta(days=1)).replace(day=1))
    for m, d in enumerate(months):
        for code, reason, amount in OVERHEAD:
            s.add(
                Entry(
                    space=space.id,
                    vehicle=None,
                    contract=None,
                    kind="overhead",
                    amount=Decimal(amount),
                    date=str(d),
                    key=f"overhead:{code}:{m}",
                    data={"reason": reason, "branch": None, "category": code},
                )
            )
    space.data = {
        "driver": customers[1].id,
        "client": customers[40].id,
        "investor": investor.id,
        "closed_months": [],
        "seed_count": count,
        "last_billed": str(today),
        "seed_version": "taxi-1",
    }
    s.add(
        Event(
            space=space.id,
            title="Личное пространство готово · 90 дней истории",
            role="system",
            data={"seed": count},
        )
    )
    s.flush()
    return space


# ───────── Пул готовых пространств ─────────
# Посев 90 дней истории занимает ~3 с. Воркер держит пару готовых пространств,
# и вход гостя забирает одно из них за миллисекунды. Заготовки живут в пределах
# своих суток МСК (посев зависит от даты) и не участвуют в биллинге и эскалациях.
POOL_SIZE = 2


def pool_day():
    return str(now().astimezone(ZoneInfo("Europe/Moscow")).date())


def claim_space(s):
    """Готовое пространство из пула, а если пул пуст — новое."""
    sp = s.scalar(
        select(Space)
        .where(Space.data["pool"].astext == pool_day(), Space.data["seed_version"].astext == "taxi-1")
        .order_by(Space.created)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not sp:
        return create_space(s)
    moment = now()
    delta = moment - sp.created
    # Время «сейчас» в посеве (SLA заявок, событие готовности) сдвигаем на момент выдачи
    for t in s.scalars(select(Item).where(Item.space == sp.id, Item.kind == "ticket")):
        shifted = {
            k: (datetime.fromisoformat(t.data[k]) + delta).isoformat()
            for k in ("due", "opened")
            if t.data.get(k)
        }
        if shifted:
            t.data = {**t.data, **shifted}
    for e in s.scalars(select(Event).where(Event.space == sp.id)):
        e.created = e.created + delta
    data = dict(sp.data)
    data.pop("pool", None)
    sp.data = data
    sp.created = sp.touched = moment
    sp.token = secrets.token_hex(32)
    return sp


def refill_pool(s):
    """Вызывается воркером: удаляет заготовки прошлых суток и досоздаёт одну за раз."""
    day = pool_day()
    for old in s.scalars(
        select(Space).where(
            Space.data.has_key("pool"), (Space.data["pool"].astext != day) | Space.data["seed_version"].astext.is_distinct_from("taxi-1")
        )
    ):
        s.delete(old)
    ready = s.scalar(
        select(func.count()).select_from(Space).where(Space.data["pool"].astext == day, Space.data["seed_version"].astext == "taxi-1")
    )
    if ready >= POOL_SIZE:
        return False
    sp = create_space(s)
    sp.data = {**sp.data, "pool": day}
    return True
