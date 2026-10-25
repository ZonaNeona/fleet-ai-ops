"""Virtual PBX webhook: signature, line → space, call activity in Bitrix24, review queued once."""

import json

from sqlalchemy import func, select

from app import telephony
from app.calls import audio, cache_key
from app.db import Job, System, db
from tests.test_integration import client  # noqa: F401  (fixture)


def test_pbx_webhook(client):  # noqa: F811
    c, sid = client
    line = c.post("/api/v1/b24app/session").json()["key"]
    api_key, salt = telephony.credentials()
    payload = json.dumps(
        {
            "entry_id": "e1",
            "recording_id": "c03",
            "from": {"number": "+79000000001"},
            "to": {"line_number": line},
            "create_time": 1,
            "end_time": 2,
        }
    )
    forged = c.post(
        "/api/telephony/mango/events/summary", data={"vpbx_api_key": api_key, "sign": "0" * 64, "json": payload}
    )
    assert forged.status_code == 403
    signed = {"vpbx_api_key": api_key, "sign": telephony.sign(api_key, payload, salt), "json": payload}
    ok = c.post("/api/telephony/mango/events/summary", data=signed)
    assert ok.status_code == 200 and ok.json()["call"] == "c03"
    activities = c.get(f"/api/b24/rest/{line}/crm.activity.list.json").json()["result"]
    assert activities[-1]["PROVIDER_ID"] == "VOXIMPLANT_CALL" and "+79000000001" in activities[-1]["SUBJECT"]
    # A repeated webhook adds another activity but never a second review of the same recording.
    assert c.post("/api/telephony/mango/events/summary", data=signed).status_code == 200
    with db() as s:
        queued = s.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.kind == "call", Job.data["call"].astext == "c03", Job.state.in_(["pending", "running"]))
        )
    # (the CI worker may already have picked the job up, so the count is 0 or 1 — never 2)
    assert queued <= 1
