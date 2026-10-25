"""Incoming documents: rules, ledger checks and the LangGraph run with a human decision."""

from decimal import Decimal

from sqlalchemy import delete, select

from app import inbox
from app.db import Entry, Item, Job, Space, db
from app.seed import create_space
from tests.cleanup import drop_space
from tests.test_integration import client  # noqa: F401  (fixture)


def space_with_docs():
    """A space with seeded documents; its queued job is removed so the background worker does not race the test."""
    with db() as s:
        sp = create_space(s, count=70)
        s.execute(delete(Job).where(Job.space == sp.id, Job.kind == "inbox"))
        docs = {x.data["name"]: x.id for x in s.scalars(select(Item).where(Item.space == sp.id, Item.kind == "inbox"))}
        return sp.id, docs


def doc(id):
    with db() as s:
        return s.get(Item, id).data


def drop(sid):
    drop_space(sid)


def test_rules_read_each_kind():
    kind, f, conf = inbox.by_rules(
        "ПОСТАНОВЛЕНИЕ № 18810177260000012345\nпо делу об административном правонарушении\n"
        "Дата нарушения: 12.10.2026\nгосномер ДЕМО 0012\nст. 12.9 ч. 2 КоАП РФ\nСумма штрафа: 1 500 руб."
    )
    assert kind == "fine" and conf == 1.0
    assert f["number"] == "18810177260000012345" and f["plate"] == "ДЕМО 0012" and inbox.to_money(f["amount"]) == 1500
    kind, f, _ = inbox.by_rules(
        "ООО «Автосервис»\nСчёт на оплату № СТ-17 от 20.10.2026\nремонт, госномер ДЕМО 0065\nИтого к оплате: 17800 руб."
    )
    assert kind == "invoice" and f["number"] == "СТ-17" and inbox.to_money(f["amount"]) == 17800
    kind, f, _ = inbox.by_rules(
        "ВОДИТЕЛЬСКОЕ УДОСТОВЕРЕНИЕ\nФИО: Иванов Иван\nНомер: 77 21 483920\nДействительно до: 01.01.2030\nКатегории: B, B1"
    )
    assert kind == "license" and f["number"] == "77 21 483920"
    assert inbox.by_rules("Меню столовой на неделю")[0] == "other"


def test_plate_normalisation():
    assert inbox.norm_plate("a 123 bc 77") == inbox.norm_plate("А123ВС77")


def test_graph_posts_holds_and_resumes():
    from app.inbox_graph import main

    sid, docs = space_with_docs()
    try:
        main("run", list(docs.values()))
        fine = doc(docs["Фото постановления из бота"])
        assert fine["status"] == "posted", fine.get("checks")
        assert [s["node"] for s in fine["steps"]] == ["read", "classify", "validate", "review", "post"]
        with db() as s:
            charge = s.get(Entry, fine["links"]["entry"])
            assert charge.kind == "charge" and charge.contract == fine["links"]["contract"]

        twin = doc(docs["Повторное фото того же постановления"])
        assert twin["status"] == "review"
        assert any(c["label"] == "Не дубль" and not c["ok"] for c in twin["checks"])

        invoice = doc(docs["Счёт СТО.pdf"])
        assert invoice["status"] == "mismatch"
        assert any(c["label"] == "Сумма в пределах сметы" and not c["ok"] for c in invoice["checks"])

        licence = doc(docs["ВУ кандидата.jpg"])
        assert licence["status"] == "posted" and licence["links"].get("client")

        # A person approves the over-estimate invoice: the same thread resumes and closes the repair.
        main("approve", [docs["Счёт СТО.pdf"]])
        invoice = doc(docs["Счёт СТО.pdf"])
        assert invoice["status"] == "posted", invoice.get("decision")
        with db() as s:
            ticket = s.get(Item, invoice["links"]["ticket"])
            assert ticket.data["status"] == "quality"
            assert Decimal(ticket.data["actual"]) == inbox.to_money(invoice["values"]["amount"])

        main("reject", [docs["Повторное фото того же постановления"]])
        assert doc(docs["Повторное фото того же постановления"])["status"] == "rejected"
    finally:
        drop(sid)


def test_api_lists_and_guards_decisions(client):  # noqa: F811
    c, sid = client
    r = c.get("/api/v1/inbox")
    assert r.status_code == 200 and r.json()["can_decide"]
    created = c.post("/api/v1/inbox", json={"sample": "license"})
    assert created.status_code == 200 and created.json()["status"] == "new"
    # Not waiting for a decision yet.
    assert c.post(f"/api/v1/inbox/{created.json()['id']}/decide", json={"approve": True}).status_code == 409
    with db() as s:
        sp = s.get(Space, sid)
        sp.role = "driver"
    assert c.get("/api/v1/inbox").status_code == 403
