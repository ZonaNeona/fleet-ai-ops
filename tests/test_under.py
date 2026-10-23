import json, time, secrets
from types import SimpleNamespace
from datetime import timedelta
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, func, text
from app.db import db, Space, Item, Job, Event, now
from app.seed import create_space
from app.agent import execute, confirm, tools_for
from app.rag import search, chunks
from app.integrations import sign, verify_context, ingest, Ingest, enqueue
from tests.test_integration import client


def test_chunking_overlap():
    result = chunks("A" * 1500)
    assert len(result) > 1 and result[0][-90:] == result[1][:90]


@pytest.mark.parametrize(
    "query,expected",
    [
        ("Какие документы нужны водителю?", "driver-documents"),
        ("Что делать при ДТП?", "accident"),
        ("Как вернуть залог?", "deposit"),
        ("Как приготовить борщ?", None),
        ("Какова масса Юпитера?", None),
    ],
)
def test_real_hybrid_retrieval(query, expected):
    r = search(query)
    if expected:
        assert any(c["id"].startswith(expected) for c in r["accepted"])
    else:
        assert not r["accepted"]
    assert all(len(step["title"]) > 0 for step in r["trace"])


def test_tools_scope_and_confirmation(client):
    c, sid = client
    with db() as s:
        sp = s.get(Space, sid)
        sp.role = "driver"
    own = execute(sid, "driver", "list_vehicles", {}, "list")["vehicles"]
    assert own
    with pytest.raises(HTTPException):
        execute(sid, "service", "get_balance", {}, "denied")
    with pytest.raises(HTTPException):
        execute(
            sid,
            "driver",
            "create_ticket",
            {
                "vehicle_code": "EC-9999",
                "title": "Проверка",
                "description": "Чужая машина",
            },
            "foreign",
        )
    with db() as s:
        before = s.scalar(
            select(func.count())
            .select_from(Item)
            .where(Item.space == sid, Item.kind == "ticket")
        )
    draft = execute(
        sid,
        "driver",
        "create_ticket",
        {
            "vehicle_code": own[0]["code"],
            "title": "Тест подвески",
            "description": "Стучит подвеска",
        },
        "draft",
    )["draft"]
    with db() as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(Item)
                .where(Item.space == sid, Item.kind == "ticket")
            )
            == before
        )
    r = c.post("/api/v1/under/drafts/" + draft["id"] + "/confirm", json={})
    assert r.status_code == 200
    again = c.post("/api/v1/under/drafts/" + draft["id"] + "/confirm", json={})
    assert again.json()["id"] == r.json()["id"]
    with db() as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(Item)
                .where(Item.space == sid, Item.kind == "ticket")
            )
            == before + 1
        )
        s.get(Space, sid).role = "owner"
    assert (
        c.post("/api/v1/under/drafts/" + draft["id"] + "/confirm", json={}).status_code
        == 404
    )


def test_draft_foreign_space_and_expiry(client):
    c, sid = client
    with db() as s:
        other = create_space(s, count=2)
        oid = other.id
    try:
        draft = execute(
            oid,
            "driver",
            "create_ticket",
            {
                "vehicle_code": "TP-0002",
                "title": "Тест чужого доступа",
                "description": "Нет доступа",
            },
            "draft",
        )["draft"]
        assert (
            c.post(
                "/api/v1/under/drafts/" + draft["id"] + "/confirm", json={}
            ).status_code
            == 404
        )
        with db() as s:
            d = s.get(Item, draft["id"])
            d.data = {**d.data, "expires": (now() - timedelta(seconds=1)).isoformat()}
            sp = s.get(Space, oid)
            sp.role = "driver"
            with pytest.raises(HTTPException):
                confirm(s, sp, d.id)
    finally:
        with db() as s:
            s.delete(s.get(Space, oid))


def test_ingest_signature_repeat_and_isolation(client):
    c, sid = client
    with db() as s:
        ctx = enqueue(s, s.get(Space, sid), "telematics")
        vehicle = s.scalar(
            select(Item).where(Item.space == sid, Item.kind == "vehicle")
        )
    rows = [
        {"vehicle_code": vehicle.code, "mileage": str(vehicle.data["mileage"] + 100)}
    ]
    body = Ingest(
        context=ctx,
        rows=rows,
        signature=sign({"context": ctx, "rows": rows}),
        execution_id="TEST",
    )
    assert ingest(body)["diffs"] == 1
    assert ingest(body)["duplicate"]
    with db() as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(Item)
                .where(Item.space == sid, Item.kind == "source_record")
            )
            == 1
        )
        assert s.get(Item, vehicle.id).data["mileage"] == vehicle.data["mileage"]
    tampered = body.model_copy(deep=True)
    tampered.rows[0]["mileage"] = "1"
    with pytest.raises(HTTPException):
        ingest(tampered)
    wrong = {**ctx, "space": "0" * 32}
    with pytest.raises(HTTPException):
        verify_context(wrong)
    with db() as s:
        s.get(Space, sid).role = "driver"
    assert c.get("/api/v1/integrations").status_code == 403
    assert c.post("/api/v1/integrations/run", json={"source": "1c"}).status_code == 403


def test_log_role_scope(client):
    c, sid = client
    with db() as s:
        s.add(
            Job(
                space=sid,
                kind="ai",
                state="done",
                data={"role": "finance", "prompt": "Закрытый финансовый вопрос"},
                result={"answer": "Сумма"},
            )
        )
        s.get(Space, sid).role = "driver"
    assert "Закрытый финансовый вопрос" not in c.get("/api/v1/under/log").text
    assert (
        c.post(
            "/api/v1/under/agent", json={"prompt": "долг", "space": "foreign"}
        ).status_code
        == 200
    )


def test_expired_source_context():
    ctx = {
        "run": "a" * 32,
        "space": "b" * 32,
        "source": "1c",
        "expires": int(time.time()) - 1,
    }
    ctx["signature"] = sign(ctx)
    with pytest.raises(HTTPException):
        verify_context(ctx)


def test_webhook_log_and_telegram_confirmation(client):
    c, sid = client
    with db() as s:
        sp = s.get(Space, sid)
        sp.role = "driver"
        s.add(
            Event(
                space=sid,
                title="Вебхук водителя",
                role="driver",
                data={"channel": "telegram"},
            )
        )
        s.add(
            Event(
                space=sid,
                title="Вебхук финансиста",
                role="finance",
                data={"channel": "telegram"},
            )
        )
    log = c.get("/api/v1/under/log").json()["rows"]
    assert any(r["title"] == "Вебхук водителя" and r["type"] == "webhook" for r in log)
    assert not any(r["title"] == "Вебхук финансиста" for r in log)
    own = execute(sid, "driver", "list_vehicles", {}, "test")["vehicles"][0]
    draft = execute(
        sid,
        "driver",
        "create_ticket",
        {
            "vehicle_code": own["code"],
            "title": "Тест уведомления",
            "description": "Стучит подвеска",
        },
        "tg-test",
    )["draft"]
    with db() as s:
        result = confirm(s, s.get(Space, sid), draft["id"], via="telegram")
        job = s.scalar(
            select(Job).where(
                Job.space == sid,
                Job.kind == "notify",
                Job.data["target"].astext == result["id"],
            )
        )
        assert job.data["via"] == "telegram"


def test_agent_history_stays_in_role_and_space(client, monkeypatch):
    from app import agent

    c, sid = client
    with db() as s:
        other = create_space(s, count=2)
        oid = other.id
        for space, role, prompt, age in [
            (sid, "driver", "Моя подвеска", 0),
            (sid, "finance", "Чужие финансы", 0),
            (oid, "driver", "Другое пространство", 0),
            (sid, "driver", "Старое сообщение", 40),
        ]:
            s.add(
                Job(
                    space=space,
                    kind="ai",
                    state="done",
                    due=now() - timedelta(minutes=age),
                    data={"mode": "agent", "role": role, "prompt": prompt},
                    result={"answer": "Уточните машину"},
                )
            )
    seen = []

    def fake_completion(space, messages, **kwargs):
        seen.extend(messages)
        return {"content": "Уточнение принято"}, {
            "cost": "0",
            "tokens": 0,
            "model": "test",
        }

    monkeypatch.setattr(agent.ai, "call_chain", fake_completion)
    try:
        agent.run(
            SimpleNamespace(
                id="current-job",
                space=sid,
                data={"role": "driver", "prompt": "TP-0002"},
            )
        )
        transcript = json.dumps(seen, ensure_ascii=False)
        assert "Моя подвеска" in transcript and "TP-0002" in transcript
        assert all(
            word not in transcript
            for word in ["Чужие финансы", "Другое пространство", "Старое сообщение"]
        )
    finally:
        with db() as s:
            s.delete(s.get(Space, oid))


def test_retrieval_quality_report():
    from app.quality import run

    r = run()["retrieval"]
    assert r["hit_at_3"] >= 0.6 and r["refusals"] >= 0.6
