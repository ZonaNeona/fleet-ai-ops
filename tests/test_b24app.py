"""Bitrix24 app around the fleet: the emulated portal over HTTP, app keys, the driver card and the robot call."""

from app import b24
from app.crm import Emulator, ReadOnly
from tests.cleanup import drop_space


def test_form_arrays_parse_like_a_portal():
    params = b24.form_params(
        "fields%5BTITLE%5D=%D0%97%D0%B2%D0%BE%D0%BD%D0%BE%D0%BA&fields%5BRESPONSIBLE_ID%5D=7&id=101"
    )
    assert params == {"fields": {"TITLE": "Звонок", "RESPONSIBLE_ID": "7"}, "id": "101"}


def test_emulator_writes_and_logs():
    p = Emulator(
        {
            "deals": [{"ID": "101", "STAGE_ID": "NEW", "CATEGORY_ID": "0", "DATE_CREATE": "2026-01-01T10:00:00+03:00"}],
            "users": [],
            "categories": [],
            "statuses": [],
            "leads": [],
        }
    )
    assert (
        p.call("crm.deal.update", {"id": 101, "fields": {"STAGE_ID": "PREPARATION"}}, source="test")["result"] is True
    )
    assert p.data["deals"][0]["STAGE_ID"] == "PREPARATION" and p.data["stagehistory"][-1]["STAGE_ID"] == "PREPARATION"
    cid = p.call("crm.timeline.comment.add", {"fields": {"ENTITY_ID": 101, "ENTITY_TYPE": "deal", "COMMENT": "ok"}})[
        "result"
    ]
    assert p.call("crm.timeline.comment.list", {"filter": {"ENTITY_ID": "101"}})["result"][0]["ID"] == str(cid)
    assert [x["method"] for x in p.data["log"]] == ["crm.deal.update", "crm.timeline.comment.add"]
    try:
        p.call("crm.deal.delete", {"id": 101})
        raise AssertionError("delete must not exist")
    except ReadOnly:
        pass


def test_app_round_trip(monkeypatch):
    # Rental contracts start from the 61st car, so this space is larger than the shared fixture's.
    import hashlib
    import secrets

    from fastapi.testclient import TestClient

    from app.api import app
    from app.db import URL, Space, db
    from app.seed import create_space

    with db() as s:
        sp = create_space(s, count=70)
        sid = sp.id
        token = secrets.token_urlsafe(32)
        sp.token = hashlib.sha256(token.encode()).hexdigest()
    c = TestClient(app, base_url=URL)
    c.cookies.set("fleet_session", token)
    key = c.post("/api/v1/b24app/session").json()["key"]
    deals = c.get(f"/api/b24/rest/{key}/crm.deal.list.json").json()
    assert deals["total"] > 0 and "time" in deals
    rental = next(d for d in deals["result"] if d.get("UF_CRM_CONTRACT"))
    # The app reads the driver card with its key; a wrong key is refused.
    assert c.get(f"/api/b24app/deal/{rental['ID']}", headers={"X-B24App-Key": "nope"}).status_code == 401
    info = c.get(f"/api/b24app/deal/{rental['ID']}", headers={"X-B24App-Key": key}).json()
    assert info["contract"]["code"] == rental["UF_CRM_CONTRACT"] and "ok" in info["verdict"]
    # The app writes into the portal over REST: a form-encoded comment, as PHP clients often send.
    r = c.post(
        f"/api/b24/rest/{key}/crm.timeline.comment.add.json",
        content=f"fields[ENTITY_ID]={rental['ID']}&fields[ENTITY_TYPE]=deal&fields[COMMENT]=hello",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200
    journal = c.get(f"/api/v1/b24app/journal?deal={rental['ID']}").json()
    assert journal["comments"][-1]["COMMENT"] == "hello" and journal["log"][-1]["source"] == "приложение"
    # The robot button sends the PHP handler the form a portal sends.
    sent = {}

    class Answer:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self):
            return {"ok": True}

    def fake_post(url, data=None, timeout=None):
        sent.update(url=url, data=data)
        return Answer()

    monkeypatch.setattr(b24.httpx, "post", fake_post)
    assert c.post("/api/v1/b24app/robot", json={"deal": rental["ID"]}).status_code == 200
    assert sent["url"].endswith("/robot.php")
    assert sent["data"]["document_id[2]"] == f"DEAL_{rental['ID']}" and sent["data"]["code"] == b24.ROBOT_CODE
    assert sent["data"]["auth[client_endpoint]"].endswith(f"/api/b24/rest/{key}/")
    token = c.get("/api/b24app/app-token", headers={"X-B24App-Key": key}).json()["application_token"]
    assert sent["data"]["auth[application_token]"] == token
    drop_space(sid)


def test_verdict_rules():
    assert b24.verdict({"candidate": {"experience": "2"}})["ok"] is False
    assert b24.verdict({"candidate": {"experience": "5"}})["ok"] is True
    clean = {"money": {"debt": "0", "crm_paid": "100", "paid": "100"}, "fines": [], "documents": []}
    assert b24.verdict(clean)["ok"] is True
    owed = {**clean, "money": {"debt": "4800", "crm_paid": "9600", "paid": "4800"}}
    reasons = b24.verdict(owed)["reasons"]
    assert any("долг" in r for r in reasons) and any("CRM" in r for r in reasons)
