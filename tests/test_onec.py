"""1С exchange: the OData $filter subset, the emulator's write path, an idempotent export and two-way reconciliation."""

from datetime import datetime

from sqlalchemy import select

from app import onec
from app.db import Item, db
from tests.test_integration import client  # noqa: F401  (fixture)


def test_filter_subset():
    row = {"Date": "2026-09-30T20:00:00", "Posted": True, "СуммаДокумента": 1500.0, "Number": "ТП00000001"}
    assert onec.matches(row, "Date ge datetime'2026-09-01T00:00:00' and Posted eq true")
    assert not onec.matches(row, "СуммаДокумента gt 2000")
    assert onec.matches(row, "Number eq 'ТП00000001'")
    assert onec.literal("datetime'2026-09-01T00:00:00'") == datetime(2026, 9, 1)
    for bad in ("Number like 'x'", "substringof('a', Number)"):
        try:
            onec.matches(row, bad)
            raise AssertionError(bad)
        except onec.ODataError:
            pass


def test_emulator_creates_and_posts():
    e = onec.Emulator({s: [] for s in onec.SETS})
    doc = e.post(onec.SALES, {"СуммаДокумента": 100.0, "Комментарий": "FLEET:D-1:2026-09:sale"})
    assert doc["Posted"] is False and doc["Number"] == "ТП00000001"
    e.post(f"{onec.SALES}(guid'{doc['Ref_Key']}')/Post()", {})
    assert e.get(onec.SALES, {"$filter": "Posted eq true"})["value"][0]["Ref_Key"] == doc["Ref_Key"]
    try:
        e.post(onec.COUNTERPARTIES, {"Description": "x"})
        raise AssertionError("catalogs are read-only")
    except onec.ODataError:
        pass


def test_exchange_is_idempotent_and_reconciles(client):  # noqa: F811
    c, sid = client
    assert c.get("/api/v1/onec").json()["report"] is None
    # The accountant once typed an act for the first contract by hand, with a wrong amount.
    month = onec.last_month()[0].strftime("%Y-%m")
    with db() as s:
        from app.db import Space

        sp = s.get(Space, sid)
        _, item = onec.emulated(s, sp)
        code = s.scalar(select(Item.code).where(Item.space == sid, Item.kind == "contract").order_by(Item.code))
        item.data = {**item.data, onec.SALES: [{"Ref_Key": "00000000-0000-0000-0000-000000000001", "Number": "ТП00000000",
                                                 "Date": f"{onec.last_month()[1]}T10:00:00", "Posted": True,
                                                 "СуммаДокумента": 1.0, "Комментарий": f"FLEET:{code}:{month}:sale"}]}
    first = c.post("/api/v1/onec/exchange").json()
    assert first["summary"]["exported"] >= 2
    notes = [r["note"] for r in first["rows"] if not r["ok"]]
    assert any("отличается" in n for n in notes)  # the hand-typed act
    assert any("в учёте не найдено" in n for n in notes)  # the bank payment loaded only into 1С
    again = c.post("/api/v1/onec/exchange").json()["summary"]
    assert again["exported"] == 0 and again["skipped"] == first["summary"]["exported"] + 1
    # The same base answers over HTTP with the visitor's key; a live base is never proxied.
    url = c.get("/api/v1/onec").json()["odata"]
    docs = c.get(url + onec.SALES, params={"$format": "json", "$filter": "Posted eq true"}).json()["value"]
    assert len(docs) == first["summary"]["documents"] - sum(1 for r in first["rows"] if r["kind"] == "payment" and r["doc"])
    assert c.get("/api/onec/nope/odata/standard.odata/" + onec.SALES).status_code == 401
    assert c.get(url + "Catalog_Пользователи").status_code == 400
