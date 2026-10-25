"""Free text must never fall through into an unconfirmed service request."""

import pytest
from sqlalchemy import func, select

from app import telegram
from app.db import Item, Space, db
from tests.test_integration import client


def setup_driver(sid, *, wait=None):
    with db() as s:
        sp = s.get(Space, sid)
        sp.role = "driver"
        sp.data = {**sp.data, "tg_wait": wait}


def update(sid, key, text=None, callback=None):
    user = {"id": "web:" + sid}
    message = {"message_id": key, "chat": {"id": 0, "type": "private"}, "from": user}
    event = {"update_id": key}
    if callback:
        event["callback_query"] = {"id": key, "from": user, "message": message, "data": callback}
    else:
        event["message"] = {**message, "text": text}
    return telegram.simulate({"space": sid, "update": event})


def tickets(sid):
    with db() as s:
        return s.scalar(select(func.count()).select_from(Item).where(Item.space == sid, Item.kind == "ticket"))


@pytest.mark.parametrize("navigation", ["/menu", "/start", "menu", "d:balance", None])
def test_price_question_after_ticket_prompt_goes_to_ai(client, monkeypatch, navigation):
    _, sid = client
    setup_driver(sid)
    update(sid, "request-ticket", callback="d:ticket")
    if navigation:
        update(
            sid,
            "navigate",
            text=navigation if navigation.startswith("/") else None,
            callback=navigation if not navigation.startswith("/") else None,
        )
        with db() as s:
            assert not s.get(Space, sid).data.get("tg_wait")
    calls = []

    def answer(space, role, text, key):
        calls.append((space, role, text))
        return {"answer": "Уточните автомобиль и срок аренды.", "drafts": [], "sources": []}

    monkeypatch.setattr(telegram, "agent_message", answer)
    before = tickets(sid)
    result = update(sid, "price-question", text="сколько стоит машина")
    assert calls == [(sid, "driver", "сколько стоит машина")]
    assert result["messages"][0]["text"] == "Уточните автомобиль и срок аренды."
    assert tickets(sid) == before


def test_start_offers_roles_without_registration(client):
    _, sid = client
    setup_driver(sid)
    result = update(sid, "start", text="/start")
    buttons = [b["data"] for m in result["messages"] for row in m["kb"] for b in row]
    assert "role:driver" in buttons and "role:owner" in buttons
    assert not any(b.startswith("pd:") for b in buttons)
    menu = update(sid, "pick-client", callback="role:client")
    with db() as s:
        assert s.get(Space, sid).role == "client"
    assert "Клиент проката" in menu["messages"][0]["text"]


def test_model_failure_is_an_answer_not_a_service_request(client, monkeypatch):
    from app import agent

    _, sid = client
    setup_driver(sid, wait="ticket")

    def unavailable(job):
        raise RuntimeError("Synthetic provider failure")

    monkeypatch.setattr(agent, "run", unavailable)
    before = tickets(sid)
    result = update(sid, "provider-failure", text="сколько стоит машина")
    assert "AI временно недоступен" in result["messages"][0]["text"]
    assert tickets(sid) == before


def test_photo_request_is_a_draft_until_explicit_confirmation(client):
    from app.agent import confirm

    _, sid = client
    setup_driver(sid)
    before = tickets(sid)
    with db() as s:
        sp = s.get(Space, sid)
        reply = telegram.ticket_draft_reply(
            s, sp, "Повреждение кузова", "Учебное фото", "technical", [], "photo-request"
        )
        callback = reply["kb"].inline_keyboard[0][0].callback_data
        assert callback.startswith("agentconfirm:") and "черновик" in reply["text"]
        draft_id = callback.partition(":")[2]
    assert tickets(sid) == before
    with db() as s:
        sp = s.get(Space, sid)
        first = confirm(s, sp, draft_id, via="telegram")
        assert confirm(s, sp, draft_id, via="telegram")["id"] == first["id"]
    assert tickets(sid) == before + 1


def test_vehicle_tool_exposes_daily_rates_not_sale_prices(client):
    from app.agent import execute

    _, sid = client
    setup_driver(sid)
    result = execute(sid, "driver", "list_vehicles", {}, "rates")
    assert result["vehicles"] and all(float(v["base_daily_rate_rub"]) > 0 for v in result["vehicles"])
    assert "Цена продажи здесь не задана" in result["note"]


def test_driver_document_goes_to_incoming_graph(client):
    _, sid = client
    setup_driver(sid)
    prompt = update(sid, "doc-prompt", callback="d:doc")
    assert "фото постановления" in prompt["messages"][0]["text"]
    before = tickets(sid)
    with db() as s:
        known = {x.id for x in s.scalars(select(Item).where(Item.space == sid, Item.kind == "inbox"))}
    reply = update(sid, "doc-sample", callback="d:docsample")
    assert "принят" in reply["messages"][0]["text"]
    with db() as s:
        new = [x for x in s.scalars(select(Item).where(Item.space == sid, Item.kind == "inbox")) if x.id not in known]
        assert len(new) == 1 and new[0].data["source"] == "bot" and new[0].data["file"]
        assert not s.get(Space, sid).data.get("tg_wait")
    assert tickets(sid) == before


def test_owner_morning_digest(client):
    c, sid = client
    with db() as s:
        sp = s.get(Space, sid)
        sp.role = "owner"
    reply = update(sid, "digest", callback="o:digest")
    text = reply["messages"][0]["text"]
    assert "Утренняя сводка" in text and "Долг" in text
    assert c.get("/api/v1/digest").json()["text"].startswith("🌅")
