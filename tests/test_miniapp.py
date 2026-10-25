import hashlib
import hmac
import json
import time
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from test_domain import contract, ctx, do, fresh
from test_integration import client

from app.db import Entry, Item, Space, db, now
from app.domain import cansee, command, file_access, get, today
from app.miniapp import balance, fines, rental_quote
from app.seed import add
from tests.cleanup import drop_space


def become(sp, role, person=None):
    sp.role = role
    sp.data = {**sp.data, **({role: person.id} if person else {})}


def test_default_driver_has_payable_demo_debt(ctx):
    s, sp = ctx
    sp.role = "driver"
    from app.domain import visible

    cs = visible(s, sp, "contract")
    assert sum(balance(s, sp, c.id, ["charge"]) - balance(s, sp, c.id, ["payment"]) for c in cs) > 0


@pytest.mark.parametrize("days,factor", [(1, "1"), (6, "1"), (7, ".95"), (29, ".95"), (30, ".9")])
def test_quote_matches_contract(ctx, days, factor):
    s, sp = ctx
    v, person = fresh(ctx)
    payload = {
        "vehicle": v.id,
        "client": person.id,
        "start": str(today()),
        "end": str(today() + timedelta(days=days)),
        "delivery": True,
        "collection": True,
        "additional_driver": "Учебный водитель",
    }
    quote = rental_quote(s, sp, payload)
    assert Decimal(quote["rate"]) == 2000 * Decimal(factor) + 300
    assert Decimal(quote["total"]) == Decimal(quote["rate"]) * days + 3000
    result = do(ctx, "contract.create", {**payload, "quote_version": quote["version"]})
    assert result["rate"] == quote["rate"]
    assert result["quote_total"] == quote["total"]
    assert result["start_time"].endswith("T10:00:00+03:00")


def test_stale_quote_does_not_book(ctx):
    s, sp = ctx
    v, p = fresh(ctx)
    payload = {"vehicle": v.id, "client": p.id, "start": str(today()), "end": str(today() + timedelta(days=3))}
    q = rental_quote(s, sp, payload)
    v.data = {**v.data, "rate": "2500"}
    with pytest.raises(HTTPException) as exc:
        do(ctx, "contract.create", {**payload, "quote_version": q["version"]})
    assert exc.value.status_code == 409


def test_payment_retry_and_issue_dont_duplicate_deposit(ctx):
    s, sp = ctx
    v, p, c = contract(ctx)
    do(ctx, "contract.confirm", {"id": c["id"]})
    become(sp, "client", p)
    intent = do(ctx, "demo_payment.create", {"purpose": "deposit", "target": c["id"]})
    same = do(ctx, "demo_payment.create", {"purpose": "deposit", "target": c["id"]})
    assert same["id"] == intent["id"]
    paid = do(ctx, "demo_payment.confirm", {"id": intent["id"]}, "mini-retry")
    assert paid["status"] == "paid" and paid["demo"]
    assert do(ctx, "demo_payment.confirm", {"id": intent["id"]}, "mini-retry") == paid
    assert do(ctx, "demo_payment.confirm", {"id": intent["id"]})["status"] == "paid"
    sp.role = "manager"
    do(ctx, "contract.issue", {"id": c["id"]})
    assert balance(s, sp, c["id"], ["deposit"]) == 20000
    assert (
        s.scalar(
            select(func.count())
            .select_from(Entry)
            .where(Entry.space == sp.id, Entry.contract == c["id"], Entry.kind == "deposit")
        )
        == 1
    )


def test_cancel_paid_booking_creates_refund_request(ctx):
    s, sp = ctx
    v, p, c = contract(ctx)
    do(ctx, "contract.confirm", {"id": c["id"]})
    become(sp, "client", p)
    payment = do(ctx, "demo_payment.create", {"purpose": "deposit", "target": c["id"]})
    do(ctx, "demo_payment.confirm", {"id": payment["id"]})
    cancelled = do(ctx, "contract.cancel", {"id": c["id"]})
    assert cancelled["refund_status"] == "pending"
    assert balance(s, sp, c["id"], ["deposit", "deposit_release"]) == 20000
    sp.role = "finance"
    refunded = do(ctx, "deposit.refund", {"contract": c["id"], "amount": "20000", "reason": "Отмена учебной брони"})
    assert refunded["refund_status"] == "completed"
    assert balance(s, sp, c["id"], ["deposit", "deposit_release"]) == 0


def test_payment_expiry_changed_debt_and_closed_period(ctx):
    s, sp = ctx
    v, p, c = contract(ctx, "taxi")
    do(ctx, "contract.confirm", {"id": c["id"]})
    do(ctx, "contract.issue", {"id": c["id"]})
    from app.domain import post

    post(s, sp, "charge", "1000", v.id, c["id"])
    s.flush()
    become(sp, "driver", p)
    intent = do(ctx, "demo_payment.create", {"purpose": "rent", "target": c["id"]})
    item = get(s, sp, intent["id"])
    item.data = {**item.data, "expires": (now() - timedelta(seconds=1)).isoformat()}
    with pytest.raises(HTTPException):
        do(ctx, "demo_payment.confirm", {"id": item.id})
    item.data = {**item.data, "expires": (now() + timedelta(minutes=5)).isoformat()}
    post(s, sp, "payment", "1", v.id, c["id"])
    s.flush()
    with pytest.raises(HTTPException):
        do(ctx, "demo_payment.confirm", {"id": item.id})
    fresh_intent = do(ctx, "demo_payment.create", {"purpose": "rent", "target": c["id"]})
    sp.data = {**sp.data, "closed_months": [str(today())[:7]]}
    with pytest.raises(HTTPException):
        do(ctx, "demo_payment.confirm", {"id": fresh_intent["id"]})


def test_payment_scope(ctx):
    s, sp = ctx
    v, p, c = contract(ctx)
    do(ctx, "contract.confirm", {"id": c["id"]})
    become(sp, "client")
    sp.data = {**sp.data, "client": "not-this-client"}
    with pytest.raises(HTTPException) as exc:
        do(ctx, "demo_payment.create", {"purpose": "deposit", "target": c["id"]})
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException):
        do(ctx, "payment.create", {"contract": c["id"], "amount": "1"})


def test_fine_payment_separate_from_rent_and_survives_sync(ctx):
    s, sp = ctx
    v, p, c = contract(ctx, "taxi")
    do(ctx, "contract.confirm", {"id": c["id"]})
    do(ctx, "contract.issue", {"id": c["id"]})
    fine = add(
        s,
        sp.id,
        "source_record",
        "fine-test",
        {
            "source": "fines",
            "vehicle": v.id,
            "values": {
                "external_id": "DEMO-TEST",
                "fine": "500",
                "discount_percent": 50,
                "discount_until": str(today() + timedelta(days=1)),
            },
            "at": now().isoformat(),
        },
    )
    s.flush()
    become(sp, "driver", p)
    before = balance(s, sp, c["id"], ["payment"])
    intent = do(ctx, "demo_payment.create", {"purpose": "fine", "target": fine.id})
    assert intent["amount"] == "250.00"
    do(ctx, "demo_payment.confirm", {"id": intent["id"]})
    fine.data = {**fine.data, "at": now().isoformat(), "run": "second-sync"}
    assert next(x for x in fines(s, sp) if x["id"] == fine.id)["status"] == "paid"
    assert balance(s, sp, c["id"], ["payment"]) == before
    assert s.scalar(select(Entry.amount).where(Entry.space == sp.id, Entry.kind == "fine_payment")) == 250


def test_expired_fine_discount(ctx):
    s, sp = ctx
    v, p, c = contract(ctx, "taxi")
    fine = add(
        s,
        sp.id,
        "source_record",
        "expired-fine",
        {
            "source": "fines",
            "vehicle": v.id,
            "values": {"fine": "500", "discount_percent": 50, "discount_until": str(today() - timedelta(days=1))},
        },
    )
    s.flush()
    become(sp, "driver", p)
    row = next(x for x in fines(s, sp) if x["id"] == fine.id)
    assert row["due"] == "500.00" and row["discount_percent"] == 0


def test_driver_inspection_cannot_release_repair(ctx):
    s, sp = ctx
    v, p, c = contract(ctx, "taxi")
    do(ctx, "contract.confirm", {"id": c["id"]})
    do(ctx, "contract.issue", {"id": c["id"]})
    v.data = {**v.data, "status": "repair", "inspection_ok": False}
    become(sp, "driver", p)
    photos = {
        side: add(s, sp.id, "file", side, {"creator_role": "driver", "ext": ".jpg", "name": side + ".jpg"}).id
        for side in ["front", "rear", "left", "right"]
    }
    result = do(
        ctx,
        "driver.inspection",
        {
            "vehicle": v.id,
            "mileage": v.data["mileage"] + 10,
            "fuel": 50,
            "shots": photos,
            "notes": "Учебное повреждение",
        },
    )
    assert v.data["status"] == "repair" and v.data["inspection_ok"] is False
    assert result["ticket"] and result["subtype"] == "pre_shift"
    with pytest.raises(HTTPException):
        do(ctx, "vehicle.inspect", {"id": v.id})
    with pytest.raises(HTTPException):
        do(
            ctx,
            "driver.inspection",
            {"vehicle": v.id, "shots": {"front": photos["front"]}, "mileage": v.data["mileage"], "fuel": 50},
        )


def test_document_file_access_reviewer_not_service(ctx):
    s, sp = ctx
    v, p = fresh(ctx)
    become(sp, "client", p)
    f = add(s, sp.id, "file", "passport-demo", {"creator_role": "client", "ext": ".pdf", "name": "учебный.pdf"})
    s.flush()
    result = do(ctx, "client.documents", {"id": p.id, "document_files": [{"type": "passport", "file": f.id}]})
    assert result["status"] == "review" and result["documents"] == ["Паспорт"]
    sp.role = "screening"
    assert file_access(s, sp, f)
    sp.role = "service"
    assert not file_access(s, sp, f)


def init_data(token, age=0, user=77889900):
    values = {"auth_date": str(int(time.time()) - age), "user": json.dumps({"id": user})}
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(
        secret, "\n".join(f"{k}={v}" for k, v in sorted(values.items())).encode(), hashlib.sha256
    ).hexdigest()
    return urlencode(values)


def test_telegram_auth_opens_the_cabinet_at_once(client, monkeypatch):
    c, sid = client
    token = "123:synthetic-only"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    with db() as s:
        sp = s.get(Space, sid)
        sp.data = {**sp.data, "tg_user": "77889900"}
    response = c.post("/api/v1/telegram/auth", json={"initData": init_data(token)})
    assert response.status_code == 200 and response.json()["id"] == sid
    assert c.get("/api/v1/bootstrap").status_code == 200
    assert c.post("/api/v1/telegram/auth", json={"initData": init_data(token, age=601)}).status_code == 403
    assert c.post("/api/v1/telegram/auth", json={"initData": init_data(token, age=-60)}).status_code == 403
    assert c.post("/api/v1/telegram/auth", json={"initData": init_data("wrong-token")}).status_code == 403


def test_bot_start_binds_chat_after_miniapp_first_entry(client):
    from app.telegram import _space

    _, sid = client
    with db() as s:
        sp = s.get(Space, sid)
        sp.data = {**sp.data, "tg_user": "77889901"}
    with db() as s:
        sp, created = _space(s, "77889901", 77889901)
        assert not created and sp.id == sid and sp.data["tg_chat"] == "77889901"


def test_receipt_foreign_space_is_not_visible(client):
    c, sid = client
    from app.seed import create_space

    with db() as s:
        other = create_space(s, count=1)
        other_id = other.id
        receipt = add(s, other.id, "demo_payment", "PRIVATE", {"status": "paid", "client": "private"})
        rid = receipt.id
    try:
        assert c.get("/api/v1/miniapp/receipts/" + rid).status_code == 404
    finally:
        drop_space(other_id)


def test_bot_message_edit_and_app_url(client):
    from app.telegram import simulate

    c, sid = client
    with db() as s:
        sp = s.get(Space, sid)
        become(sp, "client")
    update = {
        "update_id": "test-edit",
        "callback_query": {
            "id": "cb",
            "from": {"id": "web:" + sid},
            "message": {"message_id": "previous-message", "chat": {"id": 0, "type": "private"}},
            "data": "menu",
        },
    }
    result = simulate({"update": update, "space": sid})
    assert result["messages"][0]["edit_target"] == "previous-message"
    buttons = [b for row in result["messages"][0]["kb"] for b in row]
    assert any("#tg/catalog" in (b.get("app_url") or "") for b in buttons)
    assert simulate({"update": update, "space": sid}) == result


def test_notification_rechecks_access_and_builds_scoped_link(client, monkeypatch):
    from types import SimpleNamespace

    from app import telegram, worker

    _, sid = client
    sent = []

    async def fake_send(chat, title, route):
        sent.append((chat, title, route))

    monkeypatch.setattr(telegram, "send", fake_send)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "synthetic-only")
    with db() as s:
        sp = s.get(Space, sid)
        become(sp, "driver")
        sp.data = {**sp.data, "tg_chat": "synthetic-only"}
        from app.domain import allowed_vehicle_ids

        car_id = next(iter(allowed_vehicle_ids(s, sp)))
        own = add(
            s,
            sid,
            "ticket",
            "NOTIFY-OWN",
            {"client": sp.data["driver"], "vehicle": car_id, "title": "Учебное обращение"},
        )
        foreign = add(s, sid, "ticket", "NOTIFY-FOREIGN", {"client": "another-person"})
        own_id, foreign_id = own.id, foreign.id

    def job(target):
        return SimpleNamespace(space=sid, data={"target": target, "title": "Обращение готово"})

    assert worker.notify(job("deleted-object"))["telegram"] == "out_of_scope"
    assert worker.notify(job(foreign_id))["telegram"] == "out_of_scope"
    assert not sent
    assert worker.notify(job(own_id))["telegram"] == "sent"
    assert sent[0][2] == "driver/tickets/" + own_id
    with db() as s:
        sp = s.get(Space, sid)
    assert len(sent) == 1


@pytest.mark.parametrize("edit_error", [None, "message is not modified", "message to edit not found"])
def test_bot_delivery_edits_or_records_replacement(monkeypatch, edit_error):
    import asyncio
    from types import SimpleNamespace

    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import AnswerCallbackQuery, EditMessageText

    from app import telegram

    sent = []
    closed = []

    class FakeBot:
        def __init__(self, token):
            self.session = self

        async def close(self):
            closed.append(True)

        async def answer_callback_query(self, cb):
            raise TelegramBadRequest(method=AnswerCallbackQuery(callback_query_id=cb), message="query is too old")

        async def edit_message_text(self, **kwargs):
            if edit_error:
                raise TelegramBadRequest(method=EditMessageText(**kwargs), message=edit_error)
            return SimpleNamespace(message_id=42)

        async def send_message(self, *args, **kwargs):
            sent.append(args)
            return SimpleNamespace(message_id=43)

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "synthetic-only")
    monkeypatch.setattr(telegram, "Bot", FakeBot)
    result = asyncio.run(telegram._deliver(1, [{"text": "Меню", "edit_target": "42"}], "expired-callback"))
    replacement = edit_error == "message to edit not found"
    assert result == ([43] if replacement else ["42"])
    assert len(sent) == int(replacement) and closed == [True]


def test_bot_retry_restores_calendar_without_changing_selection(client):
    from app.telegram import simulate

    c, sid = client
    with db() as s:
        sp = s.get(Space, sid)
        become(sp, "client")
        vehicle = add(
            s,
            sid,
            "vehicle",
            "CAL-CAR",
            {"direction": "rental", "status": "ready", "rate": "2000", "model": "Учебный автомобиль"},
        )
        sp.data = {
            **sp.data,
            "tg_booking": {"vehicle": vehicle.id, "month": str(today().replace(day=1)), "start": str(today())},
        }
    update = {
        "update_id": "calendar-worker-retry",
        "callback_query": {
            "id": "cb",
            "from": {"id": "web:" + sid},
            "message": {"message_id": "calendar-message", "chat": {"id": 0, "type": "private"}},
            "data": "c:pick:" + str(today() + timedelta(days=7)),
        },
    }
    first = simulate({"update": update, "space": sid})
    assert simulate({"update": update, "space": sid}) == first
    with db() as s:
        assert s.get(Space, sid).data["tg_booking"]["end"] == str(today() + timedelta(days=7))


def test_inline_calendar_books_with_shared_price(ctx):
    from app.tg_calendar import handle

    s, sp = ctx
    v, p = fresh(ctx)
    become(sp, "client", p)
    handle(s, sp, "dates", v.id, "calendar-1")
    handle(s, sp, "pick", str(today()), "calendar-2")
    handle(s, sp, "pick", str(today() + timedelta(days=7)), "calendar-3")
    handle(s, sp, "reserve", "", "calendar-4")
    c = s.scalar(select(Item).where(Item.space == sp.id, Item.kind == "contract", Item.data["vehicle"].astext == v.id))
    assert c.data["rate"] == "1900.00" and c.data["quote_total"] == "13300.00"
