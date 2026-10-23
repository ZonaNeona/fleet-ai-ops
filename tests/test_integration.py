import hashlib, secrets, time, shutil, os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func, delete
from app.api import app
from app.db import db, Space, Item, Job, System, FILES, URL, now
from app.seed import create_space, add


@pytest.fixture
def client():
    with db() as s:
        sp = create_space(s, count=2)
        sid = sp.id
        token = secrets.token_urlsafe(32)
        sp.token = hashlib.sha256(token.encode()).hexdigest()
    with TestClient(app, base_url=URL) as client:
        client.cookies.set("fleet_session", token)
        yield client, sid
    with db() as s:
        sp = s.get(Space, sid)
        if sp:
            s.delete(sp)
    folder = (FILES / sid).resolve()
    if folder.parent == FILES.resolve() and folder.exists():
        shutil.rmtree(folder)


def test_concurrent_booking(client):
    c, sid = client
    b = c.get("/api/v1/bootstrap").json()
    v = next(v for v in b["vehicle"] if v["code"] == "TP-0001")
    payload = {
        "vehicle": v["id"],
        "client": b["client"][0]["id"],
        "start": b["today"],
        "end": str(__import__("datetime").date.fromisoformat(b["today"]) + timedelta(days=3)),
    }

    def request(_):
        return c.post(
            "/api/v1/commands",
            headers={"Idempotency-Key": secrets.token_hex(16)},
            json={"action": "contract.create", "payload": payload},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(request, range(2)))
    assert sorted(codes) == [200, 409]


def test_file_scope_and_role(client):
    c, sid = client
    c.post("/api/v1/session/role", json={"role": "driver"})
    f = c.post("/api/v1/files", files={"file": ("demo.csv", b"number,amount\nTEST,100", "text/csv")}).json()
    assert c.get("/api/v1/files/" + f["id"]).status_code == 200
    c.post("/api/v1/session/role", json={"role": "service"})
    assert c.get("/api/v1/files/" + f["id"]).status_code == 403
    with db() as s:
        vehicle = s.scalar(select(Item.id).where(Item.space == sid, Item.kind == "vehicle").limit(1))
        add(s, sid, "ticket", "ATTACHED-FILE", {"vehicle": vehicle, "photos": [f["id"]], "status": "new"})
    assert c.get("/api/v1/files/" + f["id"]).status_code == 200
    with db() as s:
        other = create_space(s, count=1)
        otherid = other.id
        foreign = s.scalar(select(Item.id).where(Item.space == otherid, Item.kind == "vehicle").limit(1))
    try:
        assert c.get("/api/v1/items/" + foreign).status_code == 404
    finally:
        with db() as s:
            s.delete(s.get(Space, otherid))


def test_webhook_deduplication(client, monkeypatch):
    c, sid = client
    secret = secrets.token_hex(16)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", secret)
    update = int(time.time() * 1000000)
    body = {"update_id": update, "message": {}}
    assert c.post("/api/v1/telegram/webhook", json=body).status_code == 403
    for _ in range(2):
        assert (
            c.post(
                "/api/v1/telegram/webhook", json=body, headers={"X-Telegram-Bot-Api-Secret-Token": secret}
            ).status_code
            == 200
        )
    with db() as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.kind == "telegram", Job.data["update_id"].astext == str(update))
            )
            == 1
        )
        s.execute(delete(Job).where(Job.kind == "telegram", Job.data["update_id"].astext == str(update)))
        s.execute(delete(System).where(System.key == "tg:" + str(update)))


def test_worker_recovers_expired_lease(client):
    _, sid = client
    with db() as s:
        job = Job(
            space=sid,
            kind="notify",
            state="running",
            attempts=1,
            lease=now() - timedelta(seconds=1),
            data={"title": "Проверка восстановления", "role": "owner"},
            result={},
        )
        s.add(job)
        s.flush()
        jid = job.id
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        with db() as s:
            job = s.get(Job, jid)
            state = job.state
            attempts = job.attempts
        if state == "done":
            break
        time.sleep(0.5)
    assert state == "done" and attempts == 2


def test_origin_and_invalid_document(client):
    c, sid = client
    assert (
        c.post(
            "/api/v1/session/role", json={"role": "owner"}, headers={"Origin": "https://unrelated.example"}
        ).status_code
        == 403
    )
    assert c.get("/api/v1/documents/unknown?format=html").status_code == 400


def test_miniapp_preserves_desktop_session(client, monkeypatch):
    import hmac, json
    from urllib.parse import urlencode

    c, sid = client
    bot_token = "123456:synthetic-test-token"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", bot_token)
    with db() as s:
        sp = s.get(Space, sid)
        sp.data = {**sp.data, "tg_user": "55667788"}
    values = {"auth_date": str(int(time.time())), "user": json.dumps({"id": 55667788})}
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(
        secret, "\n".join(f"{k}={v}" for k, v in sorted(values.items())).encode(), hashlib.sha256
    ).hexdigest()
    with TestClient(app, base_url=URL) as mini:
        assert mini.post("/api/v1/telegram/auth", json={"initData": urlencode(values)}).json()["id"] == sid
        assert mini.get("/api/v1/session").json()["id"] == sid
    assert c.get("/api/v1/session").json()["id"] == sid
