"""Virtual PBX webhook (Mango Office format) → call in the fleet → call activity in Bitrix24 → checklist review.

The PBX POSTs form fields `vpbx_api_key`, `sign`, `json`, where sign = sha256(api_key + json + api_salt). The handler
verifies the signature, finds the visitor space by the line number, writes a call activity into the (emulated)
Bitrix24 portal and queues the review of the recording. On the public stand the «Позвонить в диспетчерскую» button
plays the PBX: it signs and sends the same webhook; the recording is one of the nine training calls.
"""

import hashlib
import json
import os
import secrets
from datetime import timedelta

from fastapi import APIRouter, Request
from sqlalchemy import select

from .db import Job, System, db, now
from .domain import fail

router = APIRouter()


def credentials():
    base = os.getenv("INTEGRATION_SECRET", "local")
    return (
        os.getenv("MANGO_API_KEY") or "demo-" + hashlib.sha256(("key" + base).encode()).hexdigest()[:16],
        os.getenv("MANGO_API_SALT") or hashlib.sha256(("salt" + base).encode()).hexdigest()[:24],
    )


def sign(api_key, payload, salt):
    return hashlib.sha256((api_key + payload + salt).encode()).hexdigest()


@router.post("/api/telephony/mango/events/summary")
async def mango_summary(request: Request):
    form = await request.form()
    api_key, salt = credentials()
    payload = str(form.get("json") or "")
    if form.get("vpbx_api_key") != api_key or not secrets.compare_digest(
        str(form.get("sign") or ""), sign(api_key, payload, salt)
    ):
        fail("Неверная подпись АТС", 403)
    event = json.loads(payload)
    import anyio

    return await anyio.to_thread.run_sync(handle, event)


def handle(event):
    from .b24 import portal_call, space_of
    from .calls import index

    space = space_of(str(event.get("to", {}).get("line_number") or ""))
    if not space:
        fail("Неизвестная линия", 404)
    recording = str(event.get("recording_id") or "")
    known = {c["id"]: c for c in index()}
    if recording not in known:
        fail("Запись не найдена", 404)
    call = known[recording]
    phone = event.get("from", {}).get("number", "")
    activity = portal_call(
        space,
        "crm.activity.add",
        {
            "fields": {
                "OWNER_TYPE_ID": 2,
                "OWNER_ID": event.get("deal_id") or 0,
                "TYPE_ID": 2,
                "DIRECTION": 1,
                "SUBJECT": f"Входящий звонок {phone} · {call['title']}",
                "PROVIDER_ID": "VOXIMPLANT_CALL",
                "COMMUNICATIONS": [{"VALUE": phone, "TYPE": "PHONE"}],
                "DESCRIPTION": f"Запись {recording}, {round(call['seconds'])} с. Разбор по чек-листу — в разделе «Звонки».",
                "START_TIME": event.get("create_time"),
                "END_TIME": event.get("end_time"),
            }
        },
        "АТС",
    )
    with db() as s:
        busy = s.scalar(
            select(Job).where(
                Job.kind == "call", Job.data["call"].astext == recording, Job.state.in_(["pending", "running"])
            )
        )
        from .calls import audio, cache_key

        if not busy and not s.get(System, cache_key(recording, audio(recording))):
            s.add(Job(space=space, kind="call", data={"call": recording, "role": "owner"}))
    result = activity["result"] if isinstance(activity, dict) else None
    return {"activity": result, "call": recording, "title": call["title"]}


@router.post("/api/v1/telephony/simulate")
def simulate(body: dict, request: Request):
    """Plays the PBX for the visitor: a signed summary webhook for one of the training recordings."""
    import httpx

    from .api import auth
    from .b24 import key_for
    from .calls import index
    from .db import URL

    with db() as s:
        sp = auth(s, request)
        if sp.role not in ("owner", "admin", "manager"):
            fail("Звонки диспетчерской доступны собственнику и менеджеру", 403)
        line = key_for(s, sp)
    ids = [c["id"] for c in index()]
    recording = body.get("call") if body.get("call") in ids else secrets.choice(ids)
    start = now() - timedelta(minutes=2)
    payload = json.dumps(
        {
            "entry_id": secrets.token_hex(8),
            "call_direction": 1,
            "recording_id": recording,
            "from": {"number": f"+7900{secrets.randbelow(10_000_000):07d}"},
            "to": {"extension": "101", "line_number": line},
            "create_time": int(start.timestamp()),
            "end_time": int(now().timestamp()),
            "talk_time": 45,
        },
        ensure_ascii=False,
    )
    api_key, salt = credentials()
    r = httpx.post(
        os.getenv("PBX_WEBHOOK_URL", os.getenv("B24_EMULATOR_URL", URL)).rstrip("/")
        + "/api/telephony/mango/events/summary",
        data={"vpbx_api_key": api_key, "sign": sign(api_key, payload, salt), "json": payload},
        timeout=30,
    )
    if r.status_code != 200:
        fail(f"Вебхук АТС не принят: {r.text[:200]}", 502)
    return {**r.json(), "webhook": {"format": "Mango Office · events/summary", "signed": True}}
