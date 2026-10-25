"""Operations and payments: limits per visitor, metrics, the report cache, YooKassa checkout → notification → ledger,
a repeated notification, a forged one, and a refund."""

import os
import secrets

from sqlalchemy import func, select

from app import ops, payments
from app.db import Entry, db
from app.seed import add
from tests.test_integration import client  # noqa: F401  (fixture)


def test_fixed_window_limit():
    ident = "test-" + secrets.token_hex(4)
    assert all(ops.allow("unit", ident, 3, 60) for _ in range(3))
    assert not ops.allow("unit", ident, 3, 60)
    assert ops.allow("unit", ident + "-other", 3, 60)


def test_metrics_and_console(client):  # noqa: F811
    c, _ = client
    c.get("/api/v1/bootstrap")
    text = c.get("/api/metrics").text
    assert "fleet_http_request_seconds_bucket" in text and "fleet_jobs" in text and "fleet_ai_spend_usd_today" in text
    view = c.get("/api/v1/observability").json()
    assert any(r["route"] == "GET /api/v1/bootstrap" for r in view["routes"]) and "queue" in view
    assert view["redis"]["enabled"] == bool(os.getenv("REDIS_URL"))


def test_report_cache_follows_changes(client):  # noqa: F811
    c, sid = client
    first = c.get("/api/v1/report")
    second = c.get("/api/v1/report")
    assert first.json() == second.json()
    if os.getenv("REDIS_URL"):
        assert first.headers["x-cache"] == "miss" and second.headers["x-cache"] == "hit"
        with db() as s:  # any commit that touches the space — here the worker or another tab adding an item
            add(s, sid, "note", "CACHE-TEST", {})
        assert c.get("/api/v1/report").headers["x-cache"] == "miss"
    else:
        assert second.headers["x-cache"] == "miss"


def test_yookassa_emulator_round_trip(client):  # noqa: F811
    c, sid = client
    c.post("/api/v1/session/role", json={"role": "driver"})
    state = c.get("/api/v1/miniapp/state").json()
    debt = next(x for x in state["contracts"] if float(x["debt"]) > 0)
    intent = c.post(
        "/api/v1/commands",
        json={"action": "demo_payment.create", "payload": {"purpose": "rent", "target": debt["id"]}},
        headers={"Idempotency-Key": secrets.token_hex(8)},
    ).json()
    started = c.post(f"/api/v1/payments/{intent['id']}/yookassa", json={"back": "/?tg=1#tg/profile"}).json()
    assert started["mode"] == "emulator" and started["confirmation_url"].endswith(started["provider_id"])
    # The same payment asked twice is one provider payment (Idempotence-Key).
    assert c.post(f"/api/v1/payments/{intent['id']}/yookassa", json={}).json()["provider_id"] == started["provider_id"]
    page = c.get(f"/api/pay/yookassa/checkout/{started['provider_id']}")
    assert page.status_code == 200 and "ТЕСТОВЫЙ МАГАЗИН" in page.text
    done = c.post(
        f"/api/pay/yookassa/checkout/{started['provider_id']}", data={"action": "pay"}, follow_redirects=False
    )
    assert done.status_code == 303 and done.headers["location"].endswith("#tg/profile")
    assert c.get(f"/api/v1/items/{intent['id']}").json()["status"] == "paid"
    key = "yookassa:" + started["provider_id"]

    def posted(k):
        with db() as s:
            return s.scalar(select(func.count()).select_from(Entry).where(Entry.space == sid, Entry.key == k))

    assert posted(key) == 1
    # YooKassa may deliver the notification again; a forged body with another amount is re-read and changes nothing.
    again = c.post(
        "/api/pay/yookassa/webhook", json={"event": "payment.succeeded", "object": {"id": started["provider_id"]}}
    ).json()
    assert again["status"] == "duplicate" and posted(key) == 1
    forged = {"event": "payment.succeeded", "object": {"id": started["provider_id"], "amount": {"value": "1.00"}}}
    assert c.post("/api/pay/yookassa/webhook", json=forged).json()["status"] == "duplicate"
    assert (
        c.post("/api/pay/yookassa/webhook", json={"event": "payment.succeeded", "object": {"id": "nope"}}).json()["ok"]
        is False
    )
    # A driver cannot refund; the owner can, once.
    assert c.post(f"/api/v1/payments/{intent['id']}/refund").status_code == 403
    c.post("/api/v1/session/role", json={"role": "owner"})
    assert c.post(f"/api/v1/payments/{intent['id']}/refund").status_code == 200
    assert c.post(f"/api/v1/payments/{intent['id']}/refund").status_code == 409
    with db() as s:
        amounts = s.scalars(
            select(Entry.amount).where(Entry.space == sid, Entry.data["receipt"].astext == intent["id"])
        ).all()
    assert len(amounts) == 2 and sum(amounts) == 0
    journal = c.get("/api/v1/payments").json()
    steps = [x["step"] for x in journal["payments"][0]["log"]]
    assert steps[0] == "Создан платёж в ЮKassa" and "Запрошен возврат" in steps


def test_safe_back_only_local_paths():
    assert payments.safe_back("//evil.example/x") == "/?tg=1#tg/profile"
    assert payments.safe_back("https://evil.example") == "/?tg=1#tg/profile"
    assert payments.safe_back("/?tg=1#tg/driver") == "/?tg=1#tg/driver"
