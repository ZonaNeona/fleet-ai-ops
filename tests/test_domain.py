import pytest, secrets
from decimal import Decimal
from datetime import datetime, timedelta
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from app.db import Session, Item, Entry, Booking, Space, now
from app.seed import create_space, add
from app.domain import command, calendar, money, today, visible, cansee, post, get
from app.reports import report


@pytest.fixture
def ctx():
    s = Session()
    try:
        sp = create_space(s, count=8)
        s.flush()
        yield s, sp
    finally:
        s.rollback()
        s.close()


def do(ctx, action, p={}, key=None):
    s, sp = ctx
    r = command(s, sp, action, p, key or secrets.token_hex(12))
    s.flush()
    return r


def fresh(ctx, direction="rental"):
    s, sp = ctx
    client = s.scalar(select(Item).where(Item.space == sp.id, Item.kind == "client", Item.code == "CL-001"))
    v = add(
        s,
        sp.id,
        "vehicle",
        "NEW-" + secrets.token_hex(4),
        {
            "model": "Тестовый автомобиль",
            "direction": direction,
            "status": "ready",
            "branch": "mitino",
            "rate": "2000",
            "mileage": 1000,
            "fuel": 80,
            "inspection_ok": True,
            "investor": None,
        },
    )
    s.flush()
    return v, client


def contract(ctx, direction="rental"):
    v, c = fresh(ctx, direction)
    x = do(
        ctx,
        "contract.create",
        {
            "vehicle": v.id,
            "client": c.id,
            "start": str(today()),
            "end": str(today() + timedelta(days=5)),
            "schedule": "7/0",
        },
    )
    if direction == "buyout":
        x = do(ctx, "contract.approve_terms", {"id": x["id"]})
    return v, c, x


def test_decimal_money():
    assert money("0.10") + money("0.20") == Decimal(".30")
    for x in ["NaN", "Infinity", "abc"]:
        with pytest.raises(HTTPException):
            money(x)


def test_buyout_offer_requires_financier(ctx):
    v, c = fresh(ctx, "buyout")
    x = do(
        ctx,
        "contract.create",
        {"vehicle": v.id, "client": c.id, "start": str(today()), "end": str(today() + timedelta(days=30))},
    )
    with pytest.raises(HTTPException):
        do(ctx, "contract.confirm", {"id": x["id"]})
    ctx[1].role = "manager"
    with pytest.raises(HTTPException):
        do(ctx, "contract.approve_terms", {"id": x["id"]})
    ctx[1].role = "finance"
    do(
        ctx,
        "contract.approve_terms",
        {"id": x["id"], "rate": "1800", "final_payment": "123000", "reason": "Утверждено"},
    )
    ctx[1].role = "manager"
    r = do(ctx, "contract.confirm", {"id": x["id"]})
    assert r["rate"] == "1800.00" and r["proposal"]["rate"] == "2000.00"


def test_service_slot_and_substitute(ctx):
    v, c, x = contract(ctx)
    do(ctx, "contract.confirm", {"id": x["id"]})
    do(ctx, "contract.issue", {"id": x["id"]})
    ticket = do(ctx, "ticket.create", {"vehicle": v.id, "title": "Нужен ремонт"})
    do(ctx, "ticket.schedule", {"id": ticket["id"], "day": str(today() + timedelta(days=1)), "slot": "11:00"})
    another = do(ctx, "ticket.create", {"vehicle": v.id, "title": "Осмотр"})
    with pytest.raises(HTTPException) as e:
        do(
            ctx,
            "ticket.schedule",
            {"id": another["id"], "day": str(today() + timedelta(days=1)), "slot": "11:00"},
        )
    assert e.value.status_code == 409
    do(ctx, "ticket.estimate", {"id": ticket["id"], "amount": "500", "payer": "company"})
    do(ctx, "ticket.approve", {"id": ticket["id"]})
    replacement, _ = fresh(ctx)
    r = do(
        ctx,
        "ticket.substitute",
        {"id": ticket["id"], "vehicle": replacement.id, "end": str(today() + timedelta(days=2))},
    )
    sub = get(ctx[0], ctx[1], r["substitute_contract"])
    assert sub.data["substitution_for"] == x["id"] and sub.data["status"] == "draft"
    do(ctx, "contract.confirm", {"id": sub.id})
    do(ctx, "contract.issue", {"id": sub.id})
    assert get(ctx[0], ctx[1], x["id"]).data["holidays"] == []


def test_payment_allocation_partial_and_reversal(ctx):
    from app.reports import payment_allocation

    v, c, x = contract(ctx)
    s, sp = ctx
    post(s, sp, "charge", "100", v.id, x["id"], "Первое")
    post(s, sp, "charge", "200", v.id, x["id"], "Второе")
    post(s, sp, "payment", "150", v.id, x["id"], "Платёж")
    s.flush()
    r = payment_allocation(s, sp, x["id"])
    assert sum(Decimal(a["remaining"]) for a in r["rows"]) == 150
    post(s, sp, "payment", "-50", v.id, x["id"], "Сторно оплаты")
    post(s, sp, "charge", "-20", v.id, x["id"], "Корректировка")
    s.flush()
    r = payment_allocation(s, sp, x["id"])
    assert sum(Decimal(a["remaining"]) for a in r["rows"]) == 180


def test_calendar_free_weekend_and_final():
    d = {
        "start": "2026-10-05",
        "end": "2026-10-11",
        "rate": "2000",
        "schedule": "5/2",
        "free_first": True,
        "direction": "taxi",
        "holidays": ["2026-10-07"],
    }
    rows = calendar(d)
    assert sum(Decimal(r["amount"]) for r in rows) == Decimal("6000")
    d.update(direction="buyout", final_payment="150000")
    assert calendar(d)[-1]["amount"] == "150000.00"


def test_rental_has_no_weekend_and_exclusive_end():
    d = {
        "start": "2026-10-09",
        "end": "2026-10-12",
        "rate": "1000",
        "schedule": "5/2",
        "direction": "rental",
        "free_first": False,
    }
    assert sum(Decimal(r["amount"]) for r in calendar(d)) == 3000


def test_scope_isolation(ctx):
    s, sp = ctx
    other = create_space(s, count=1)
    s.flush()
    v = s.scalar(select(Item).where(Item.space == other.id, Item.kind == "vehicle"))
    with pytest.raises(HTTPException) as e:
        get(s, sp, v.id)
    assert e.value.status_code == 404


def test_driver_own_contract(ctx):
    s, sp = ctx
    sp.role = "driver"
    cs = visible(s, sp, "contract")
    assert cs and all(c.data["client"] == sp.data["driver"] for c in cs)
    with pytest.raises(HTTPException) as e:
        do(ctx, "payment.create", {"contract": cs[0].id, "amount": "10"})
    assert e.value.status_code == 403


def test_screening_cannot_read_finance(ctx):
    s, sp = ctx
    sp.role = "screening"
    assert visible(s, sp, "contract") == [] and visible(s, sp, "vehicle") == []


def test_booking_conflict(ctx):
    v, c, x = contract(ctx)
    with pytest.raises(IntegrityError):
        do(
            ctx,
            "contract.create",
            {"vehicle": v.id, "client": c.id, "start": str(today()), "end": str(today() + timedelta(days=5))},
        )


def test_idempotency(ctx):
    v, c, x = contract(ctx)
    p = {"contract": x["id"], "amount": "1234"}
    a = do(ctx, "payment.create", p, "unique-payment")
    b = do(ctx, "payment.create", p, "unique-payment")
    assert a == b
    s, sp = ctx
    assert (
        s.scalar(
            select(func.count())
            .select_from(Entry)
            .where(Entry.space == sp.id, Entry.contract == x["id"], Entry.kind == "payment")
        )
        == 1
    )
    with pytest.raises(HTTPException):
        do(ctx, "payment.create", {"contract": x["id"], "amount": "1235"}, "unique-payment")


def test_issue_and_deposit_not_income(ctx):
    v, c, x = contract(ctx)
    do(ctx, "contract.confirm", {"id": x["id"]})
    do(ctx, "contract.issue", {"id": x["id"]})
    s, sp = ctx
    es = s.scalars(select(Entry).where(Entry.space == sp.id, Entry.contract == x["id"])).all()
    assert sum(e.amount for e in es if e.kind == "deposit") == 20000
    assert sum(e.amount for e in es if e.kind == "charge") == 2000


def test_stale_version(ctx):
    v, c, x = contract(ctx)
    do(ctx, "contract.confirm", {"id": x["id"]})
    with pytest.raises(HTTPException) as e:
        do(ctx, "contract.issue", {"id": x["id"], "version": 1})
    assert e.value.status_code == 409


def test_unapproved_client(ctx):
    v, c, x = contract(ctx)
    c.data = {**c.data, "status": "review"}
    with pytest.raises(HTTPException):
        do(ctx, "contract.confirm", {"id": x["id"]})


def test_repair_full_cycle(ctx):
    v, c = fresh(ctx)
    x = do(ctx, "ticket.create", {"vehicle": v.id, "title": "Поломка"})
    do(ctx, "ticket.estimate", {"id": x["id"], "amount": "5000", "payer": "company"})
    do(ctx, "ticket.approve", {"id": x["id"]})
    do(ctx, "ticket.start", {"id": x["id"]})
    do(ctx, "ticket.complete", {"id": x["id"], "amount": "4500"})
    with pytest.raises(HTTPException):
        do(ctx, "ticket.release", {"id": x["id"]})
    do(ctx, "vehicle.inspect", {"id": v.id, "mileage": 1100, "fuel": 50})
    do(ctx, "ticket.release", {"id": x["id"]})
    assert v.data["status"] == "ready"
    s, sp = ctx
    assert (
        s.scalar(
            select(func.sum(Entry.amount)).where(
                Entry.space == sp.id, Entry.vehicle == v.id, Entry.kind == "expense"
            )
        )
        == 4500
    )


def test_unapproved_repair(ctx):
    v, c = fresh(ctx)
    x = do(ctx, "ticket.create", {"vehicle": v.id, "title": "Поломка"})
    with pytest.raises(HTTPException):
        do(ctx, "ticket.start", {"id": x["id"]})


def test_closed_period(ctx):
    s, sp = ctx
    do(ctx, "period.close", {"month": str(today())[:7]})
    with pytest.raises(HTTPException):
        post(s, sp, "payment", 100)
    do(ctx, "period.reopen", {"month": str(today())[:7]})
    post(s, sp, "payment", 100)


def test_refund_limit(ctx):
    v, c, x = contract(ctx)
    do(ctx, "contract.confirm", {"id": x["id"]})
    do(ctx, "contract.issue", {"id": x["id"]})
    with pytest.raises(HTTPException):
        do(ctx, "deposit.refund", {"contract": x["id"], "amount": "21000", "reason": "Возврат"})
    do(ctx, "deposit.refund", {"contract": x["id"], "amount": "20000", "reason": "Возврат"})
    with pytest.raises(HTTPException):
        do(ctx, "deposit.refund", {"contract": x["id"], "amount": "1", "reason": "Повтор"})


def test_owner_settlement(ctx):
    s, sp = ctx
    v, c = fresh(ctx)
    inv = s.scalar(select(Item).where(Item.space == sp.id, Item.kind == "investor", Item.code == "INV-01"))
    v.data = {**v.data, "investor": inv.id}
    post(s, sp, "payment", 10000, v.id)
    post(s, sp, "deposit", 20000, v.id)
    post(s, sp, "expense", 1000, v.id, payer="owner")
    s.flush()
    stmt = do(ctx, "owner.statement", {"investor": inv.id, "month": str(today())[:7]})
    line = next(l for l in stmt["lines"] if l["vehicle"] == v.id)
    assert money(line["amount"]) == 6000
    do(ctx, "owner.approve", {"id": stmt["id"]})
    do(ctx, "owner.pay", {"id": stmt["id"]})
    with pytest.raises(HTTPException):
        do(ctx, "owner.pay", {"id": stmt["id"]})


def test_partial_payment_and_report(ctx):
    s, sp = ctx
    v, c, x = contract(ctx)
    do(ctx, "contract.confirm", {"id": x["id"]})
    do(ctx, "contract.issue", {"id": x["id"]})
    do(ctx, "payment.create", {"contract": x["id"], "amount": 500})
    r = report(s, sp)
    row = next(r for r in r["rows"] if r["id"] == v.id)
    assert money(row["debt"]) == 1500


def test_tariff_snapshot(ctx):
    v, c, x = contract(ctx)
    do(ctx, "tariff.create", {"name": "Новый", "direction": "rental", "rate": 9000})
    s, sp = ctx
    assert get(s, sp, x["id"]).data["rate"] == "2000.00"


def test_holidays_future(ctx):
    v, c, x = contract(ctx, "buyout")
    do(ctx, "contract.confirm", {"id": x["id"]})
    do(ctx, "contract.issue", {"id": x["id"]})
    d = str(today() + timedelta(days=2))
    do(ctx, "contract.holiday", {"id": x["id"], "start": d, "end": d})
    do(ctx, "contract.approve_holiday", {"id": x["id"]})
    s, sp = ctx
    assert next(r for r in calendar(get(s, sp, x["id"])) if r["date"] == d)["amount"] == "0.00"


def test_cancel_frees_reservation(ctx):
    v, c, x = contract(ctx)
    do(ctx, "contract.cancel", {"id": x["id"]})
    y = do(
        ctx,
        "contract.create",
        {"vehicle": v.id, "client": c.id, "start": str(today()), "end": str(today() + timedelta(days=5))},
    )
    assert y["id"] != x["id"]


@pytest.mark.parametrize("seconds,expected", [(24 * 3600, 2000), (26 * 3600, 2000), (26 * 3600 + 1, 4000)])
def test_rental_return_grace(ctx, monkeypatch, seconds, expected):
    import app.domain as d

    fixed = datetime(2026, 10, 7, 10, tzinfo=__import__("zoneinfo").ZoneInfo("Europe/Moscow"))
    monkeypatch.setattr(d, "now", lambda: fixed)
    v, c, x = contract(ctx)
    do(ctx, "contract.confirm", {"id": x["id"]})
    do(ctx, "contract.issue", {"id": x["id"]})
    returned = fixed + timedelta(seconds=seconds)
    monkeypatch.setattr(d, "now", lambda: returned)
    do(
        ctx,
        "contract.return",
        {"id": x["id"], "mileage": 1000, "fuel": 80, "returned_at": returned.isoformat()},
    )
    s, sp = ctx
    assert (
        s.scalar(
            select(func.sum(Entry.amount)).where(
                Entry.space == sp.id, Entry.contract == x["id"], Entry.kind == "charge"
            )
        )
        == expected
    )


def test_inspection_cannot_bypass_repair(ctx):
    v, c = fresh(ctx)
    t = do(ctx, "ticket.create", {"vehicle": v.id})
    do(ctx, "ticket.estimate", {"id": t["id"], "amount": 100})
    do(ctx, "ticket.approve", {"id": t["id"]})
    do(ctx, "ticket.start", {"id": t["id"]})
    with pytest.raises(HTTPException):
        do(ctx, "vehicle.inspect", {"id": v.id, "mileage": 1000, "fuel": 80})


def test_buyout_debt_blocks_transfer(ctx):
    v, c, x = contract(ctx, "buyout")
    do(ctx, "contract.confirm", {"id": x["id"]})
    do(ctx, "contract.issue", {"id": x["id"]})
    do(ctx, "contract.close_quote", {"id": x["id"], "amount": 50000})
    with pytest.raises(HTTPException):
        do(ctx, "contract.close", {"id": x["id"], "confirmed": True})
    do(ctx, "payment.create", {"contract": x["id"], "amount": 2000})
    do(ctx, "contract.close", {"id": x["id"], "confirmed": True})
    assert v.data["status"] == "sold"


def test_overhead_reconciles_filters(ctx):
    s, sp = ctx
    r = report(s, sp)
    parts = [report(s, sp, branch=b) for b in ["mitino", "vernadskogo", "kuntsevo"]]
    assert sum(money(p["overhead"]) for p in parts) == money(r["overhead"])
    assert sum(money(p["profit"]) for p in parts) == money(r["profit"])


@pytest.mark.parametrize(
    "role", ["owner", "admin", "manager", "service", "screening", "finance", "driver", "client", "investor"]
)
def test_role_read_matrix(ctx, role):
    s, sp = ctx
    sp.role = role
    for kind in ["vehicle", "client", "contract", "ticket", "investor", "statement", "tariff", "referral"]:
        assert all(cansee(s, sp, x) for x in visible(s, sp, kind))
    if role in ["manager", "service", "screening"]:
        assert report(s, sp)["revenue"] == "0"


def test_negative_and_nonfinite_amount(ctx):
    v, c, x = contract(ctx)
    for amount in ["-1", "NaN", "Infinity", "0"]:
        with pytest.raises(HTTPException):
            do(ctx, "payment.create", {"contract": x["id"], "amount": amount})


def test_owner_payout_accounts_for_loss_making_car(ctx):
    s, sp = ctx
    v, c = fresh(ctx)
    v2, c = fresh(ctx)
    inv = s.scalar(select(Item).where(Item.space == sp.id, Item.kind == "investor", Item.code == "INV-01"))
    v.data = {**v.data, "investor": inv.id}
    v2.data = {**v2.data, "investor": inv.id}
    post(s, sp, "payment", 10000, v.id)
    post(s, sp, "expense", 1000, v2.id, payer="owner")
    s.flush()
    st = do(ctx, "owner.statement", {"investor": inv.id})
    do(ctx, "owner.approve", {"id": st["id"]})
    do(ctx, "owner.pay", {"id": st["id"]})
    assert money(st["amount"]) == 6000
    assert (
        s.scalar(select(func.sum(Entry.amount)).where(Entry.space == sp.id, Entry.kind == "owner_payout"))
        == 6000
    )


def test_rental_services_snapshot(ctx):
    s, sp = ctx
    v, c = fresh(ctx)
    x = do(
        ctx,
        "contract.create",
        {
            "vehicle": v.id,
            "client": c.id,
            "start": str(today()),
            "end": str(today() + timedelta(days=5)),
            "additional_driver": "Учебный второй водитель",
            "delivery": True,
            "collection": True,
        },
    )
    assert money(x["rate"]) == 2300 and money(x["services_amount"]) == 3000
    do(ctx, "contract.confirm", {"id": x["id"]})
    do(ctx, "contract.issue", {"id": x["id"]})
    assert (
        s.scalar(
            select(func.sum(Entry.amount)).where(
                Entry.space == sp.id, Entry.contract == x["id"], Entry.kind == "charge"
            )
        )
        == 5300
    )


def test_telegram_signed_data(monkeypatch):
    import hmac, hashlib, json, time
    from urllib.parse import urlencode
    from app.telegram import validate

    token = "123456:test-synthetic-token"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)

    def signed(age=0):
        values = {"auth_date": str(int(time.time()) - age), "user": json.dumps({"id": 12345})}
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        values["hash"] = hmac.new(
            secret, "\n".join(f"{k}={v}" for k, v in sorted(values.items())).encode(), hashlib.sha256
        ).hexdigest()
        return urlencode(values)

    assert validate(signed())["id"] == 12345
    with pytest.raises(HTTPException):
        validate(signed(601))
    with pytest.raises(HTTPException):
        validate(signed().replace("12345", "99999"))


def test_pool_claim_is_fresh_and_unbilled():
    from app.seed import claim_space, pool_day

    s = Session()
    try:
        sp = create_space(s, count=8)
        sp.data = {**sp.data, "pool": pool_day()}
        sp.created = sp.touched = now() - timedelta(minutes=40)
        s.flush()
        got = claim_space(s)
        s.flush()
        assert "pool" not in got.data
        assert got.created > now() - timedelta(minutes=1)
        # SLA заявок отсчитывается от момента выдачи, а не от посева
        t = s.scalar(select(Item).where(Item.space == got.id, Item.kind == "ticket", Item.code == "SRV-201"))
        assert datetime.fromisoformat(t.data["due"]) > now() + timedelta(minutes=10)
    finally:
        s.rollback()
        s.close()
