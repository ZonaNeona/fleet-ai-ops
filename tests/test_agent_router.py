"""The agent's router: quick answers without a model, the quota they do not spend, «сделать сейчас» signals, and the
MCP server running Hermes's calls in the space and under the role of the turn in progress."""

import json
import time
from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import select

from app import agent, hermes, quick
from app.db import Item, Space, System, db, now
from app.seed import add
from tests.test_integration import client  # noqa: F401  (fixture)


def test_intent_matching_is_narrow():
    assert quick.match("Какие машины хуже всех по результату?") is quick.worst
    assert quick.match("что сделать сейчас") is quick.now_list
    assert quick.match("Почему у нас долг вырос?") is None  # «why» needs reasoning
    assert quick.match("покажи долги и машины в ремонте") is None  # two topics — one canned answer would drop half
    assert quick.match("TP-0002") is None


def test_quick_answer_uses_tools_not_the_model(client, monkeypatch):  # noqa: F811
    c, sid = client

    def no_model(*a, **k):
        raise AssertionError("a quick answer must not call the model")

    monkeypatch.setattr(agent.ai, "call_chain", no_model)
    result = agent.run(SimpleNamespace(id="j1", space=sid, data={"role": "owner", "prompt": "Какие машины хуже всех?"}))
    assert result["engine"] == "rules" and result["cost"] == "0"
    assert [s["title"] for s in result["trace"] if s["step"] == "tool"] == ["vehicle_economics"]
    assert "TP-" in result["answer"]
    # A driver asking for the fleet-wide list does not get it: the question goes to the agent instead.
    seen = []
    monkeypatch.setattr(
        agent.ai,
        "call_chain",
        lambda space, messages, **k: (seen.append(1) or {"content": "ок"}, {"cost": "0", "tokens": 0, "model": "t"}),
    )
    driver = agent.run(SimpleNamespace(id="j2", space=sid, data={"role": "driver", "prompt": "что сделать сейчас"}))
    assert driver["engine"] == "model" and seen


def test_quick_questions_do_not_spend_the_hourly_quota(client):  # noqa: F811
    c, _ = client
    for _ in range(12):
        r = c.post("/api/v1/ai", json={"mode": "agent", "prompt": "сколько нам должны?"})
        assert r.status_code == 200, r.text


def test_signals_follow_the_data(client):  # noqa: F811
    c, sid = client
    with db() as s:
        v = s.scalar(select(Item).where(Item.space == sid, Item.kind == "vehicle").order_by(Item.code))
        tid = add(
            s,
            sid,
            "ticket",
            "SRV-TEST",
            {
                "vehicle": v.id,
                "title": "Стук в подвеске",
                "status": "new",
                "due": (now() - timedelta(hours=3)).isoformat(),
            },
        ).id
    view = c.get("/api/v1/signals").json()
    overdue = [r for r in view["rows"] if r["rule"] == "ticket-overdue"]
    assert any(r["target"] == tid for r in overdue) and overdue[0]["action"]
    with db() as s:
        t = s.get(Item, tid)
        t.data = {**t.data, "status": "closed"}
    assert not any(r["target"] == tid for r in c.get("/api/v1/signals").json()["rows"])
    c.post("/api/v1/session/role", json={"role": "driver"})
    assert c.get("/api/v1/signals").status_code == 403


def test_hermes_mcp_calls_run_in_the_turns_space_and_role(client, monkeypatch):  # noqa: F811
    c, sid = client
    monkeypatch.setenv("FLEET_HERMES_MCP_KEY", "hermes-test-key")
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "crm_pipeline", "arguments": {}}}
    url = "/api/mcp?key=hermes-test-key"

    def turn(role, age=0):
        with db() as s:
            row = s.get(System, hermes.TURN_KEY)
            data = {"space": sid, "role": role, "job": "t", "at": time.time() - age}
            if row:
                row.data = data
            else:
                s.add(System(key=hermes.TURN_KEY, data=data))

    turn("owner")
    assert c.post(url, json=call).json()["result"]["isError"] is False
    turn("driver")  # the driver's own agent cannot read Bitrix24 — neither can Hermes on the driver's turn
    assert c.post(url, json=call).json()["result"]["isError"] is True
    turn("owner", age=hermes.TURN_TTL + 5)  # no turn in progress: nothing runs
    out = c.post(url, json=call).json()["result"]
    assert out["isError"] is True and "Нет активного хода" in out["content"][0]["text"]
    tools = c.post(url, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).json()["result"]["tools"]
    assert {t["name"] for t in tools} >= {"crm_pipeline", "vehicle_economics"}
    assert c.post("/api/mcp?key=wrong", json=call).status_code == 401
    with db() as s:
        assert s.get(Space, sid) is not None and json.dumps(s.get(System, hermes.TURN_KEY).data)
