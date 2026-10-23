"""Bitrix24: transport contract, sync with paging, reconciliation with the ledger, agent tools."""

import pytest
from sqlalchemy import select

from app import crm
from app.db import Item, Space, db
from app.seed import create_space
from tests.cleanup import drop_space
from tests.test_integration import client  # noqa: F401  (fixture)


def portal(n):
    return crm.Emulator({"users": [], "categories": [], "statuses": [], "leads": [], "tasks": [],
                         "deals": [{"ID": str(i), "TITLE": f"Сделка {i}", "CATEGORY_ID": str(i % 2),
                                    "DATE_CREATE": "2026-01-01T10:00:00+03:00"} for i in range(1, n + 1)]})


def test_emulator_pages_like_a_portal():
    p = portal(120)
    first = p.call("crm.deal.list", {"order": {"ID": "ASC"}})
    assert len(first["result"]) == 50 and first["total"] == 120 and first["next"] == 50
    last = p.call("crm.deal.list", {"start": 100})
    assert len(last["result"]) == 20 and "next" not in last
    only = p.call("crm.deal.list", {"filter": {"CATEGORY_ID": "1"}, "select": ["TITLE"]})
    assert only["total"] == 60 and set(only["result"][0]) == {"ID", "TITLE"}
    assert "duration" in first["time"]


def test_live_portal_is_read_only_before_any_network():
    live = crm.Live("https://example.bitrix24.ru/rest/1/secret/")
    with pytest.raises(crm.ReadOnly):
        live.call("tasks.task.add", {"fields": {"TITLE": "x"}})
    with pytest.raises(crm.ReadOnly):
        live.call("crm.deal.delete", {"id": 1})
    with pytest.raises(crm.ReadOnly):
        live.call("crm.deal.list", {"filter": {}, "unexpected": 1})


def test_sync_funnels_and_reconciliation():
    with db() as s:
        sp = create_space(s, count=70)
        sid = sp.id
        snap = s.scalar(select(Item).where(Item.space == sid, Item.kind == "crm")).data
        assert {f["key"] for f in snap["funnels"]} == {"rental", "hiring"}
        assert any(t["method"] == "crm.deal.list" for t in snap["trace"])
        assert snap["summary"]["stuck"] >= 2
        bad = [r for r in snap["reconciliation"] if not r["ok"]]
        assert len(bad) == 2 and all(float(r["diff"]) == 4800 for r in bad)
        assert all(r["ok"] for r in snap["reconciliation"] if r not in bad)
    drop_space(sid)


def test_api_and_agent_task_draft(client):  # noqa: F811
    from app.agent import confirm, execute

    c, sid = client
    r = c.get("/api/v1/crm")
    assert r.status_code == 200 and r.json()["mode"] == "emulator"
    pipeline = execute(sid, "owner", "crm_pipeline", {"funnel": "hiring"}, "k1")
    assert pipeline["funnels"][0]["key"] == "hiring"
    draft = execute(sid, "owner", "crm_task", {"title": "Перезвонить кандидату", "responsible": "hiring"}, "k2")["draft"]
    assert draft["status"] == "pending"
    with db() as s:
        sp = s.get(Space, sid)
        sp.role = "owner"
        result = confirm(s, sp, draft["id"])
    assert result["code"].startswith("B24-T")
    assert any(t["TITLE"] == "Перезвонить кандидату" for t in c.get("/api/v1/crm").json()["tasks"])
    with db() as s:
        s.get(Space, sid).role = "driver"
    assert c.get("/api/v1/crm").status_code == 403
