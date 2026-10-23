"""Call desk: audio decoding, the score formula, review caching and access."""

import pytest
from sqlalchemy import delete

from app import calls, voice
from app.ai import Answer
from app.call_scripts import CHECKLIST
from app.db import Space, System, db
from tests.test_integration import client  # noqa: F401  (fixture)


def test_recordings_decode_to_mp3():
    raw = calls.audio("c03")
    mp3, seconds = voice.to_mp3(raw)
    assert mp3 and 15 < seconds < 30
    with pytest.raises(RuntimeError):
        voice.to_mp3(b"not audio at all")


def test_score_ignores_not_applicable():
    items = [{"key": k, "status": "supported"} for k, _, _ in CHECKLIST]
    assert calls.score(items) == 100
    items[3]["status"] = "not_applicable"  # safety: no accident in this call
    items[0]["status"] = "not_found"  # greeting missing, weight 10 of 85 applicable
    assert calls.score(items) == round(100 * 75 / 85)


def test_review_is_cached_for_everyone(client, monkeypatch):  # noqa: F811
    c, sid = client
    with db() as s:
        s.execute(delete(System).where(System.key.like("call:c09:%")))
    heard = {"text": "Таксопарк, здравствуйте. Стучит спереди. Приезжайте как-нибудь.", "seconds": 17.3,
             "cost": "0.0004", "model": "google/gemini-2.5-flash-lite", "ms": 900}
    monkeypatch.setattr(voice, "transcribe", lambda space, raw: heard)
    paid = []

    def fake_call(space, model, messages, max_tokens=1800, provider="openrouter"):
        paid.append(model)
        items = [{"key": k, "status": "not_found" if k in ("deadline", "record") else "supported",
                  "evidence": "", "reason": "проверка"} for k, _, _ in CHECKLIST]
        items[3]["status"] = "not_applicable"
        return Answer(answer="Водитель сообщил о стуке; срок не назван.", fields={"items": items, "advice": "Назовите время."}), \
            {"model": model, "cost": "0.0010", "ms": 1200, "tokens": 500}

    monkeypatch.setattr("app.ai.call", fake_call)
    monkeypatch.setattr("app.ai.chain", lambda vision=False: [("openrouter", "test/model")])
    first = calls.review(sid, "c09")
    assert first["score"] == round(100 * 65 / 85) and first["stt"]["cost"] == "0.0004"
    again = calls.review(sid, "c09")
    assert again["at"] == first["at"] and len(paid) == 1
    rows = {r["id"]: r for r in c.get("/api/v1/calls").json()["rows"]}
    assert len(rows) == 9 and rows["c09"]["review"]["score"] == first["score"]
    assert c.post("/api/v1/calls/c09/review").json()["state"] == "done"
    with db() as s:
        s.execute(delete(System).where(System.key.like("call:c09:%")))
        s.get(Space, sid).role = "driver"
    assert c.get("/api/v1/calls").status_code == 403
