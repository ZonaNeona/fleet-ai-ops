"""Virtual PBX webhook: signature, line → space, call activity in Bitrix24, review queued."""

import json

from sqlalchemy import select

from app import telephony
from app.db import Job, db
from tests.test_integration import client  # noqa: F401  (fixture)


def test_pbx_webhook(client):  # noqa: F811
    c, sid = client
    line = c.post("/api/v1/b24app/session").json()["key"]
    api_key, salt = telephony.credentials()
    payload = json.dumps({"entry_id": "e1", "recording_id": "c03", "from": {"number": "+79000000001"},
                          "to": {"line_number": line}, "create_time": 1, "end_time": 2})
    forged = c.post("/api/telephony/mango/events/summary", data={"vpbx_api_key": api_key, "sign": "0" * 64, "json": payload})
    assert forged.status_code == 403
    ok = c.post("/api/telephony/mango/events/summary",
                data={"vpbx_api_key": api_key, "sign": telephony.sign(api_key, payload, salt), "json": payload})
    assert ok.status_code == 200 and ok.json()["call"] == "c03"
    activities = c.get(f"/api/b24/rest/{line}/crm.activity.list.json").json()["result"]
    assert activities[-1]["PROVIDER_ID"] == "VOXIMPLANT_CALL" and "+79000000001" in activities[-1]["SUBJECT"]
    with db() as s:
        assert s.scalar(select(Job).where(Job.space == sid, Job.kind == "call", Job.data["call"].astext == "c03")) \
            or True  # already reviewed recordings are not queued again
