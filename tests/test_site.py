"""Client site: server-rendered catalog, a car page with the server's price, canonical URLs, crawlers' files, and a
request that becomes a lead and a deal in the visitor's Bitrix24 — opening a demo space when there is none."""

import hashlib
import re

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import site
from app.api import app
from app.db import URL, Space, db
from tests.cleanup import drop_space


def client():
    return TestClient(app, base_url=URL)


def test_catalog_and_car_page():
    c = client()
    catalog = c.get("/auto")
    assert catalog.status_code == 200 and "Haval Jolion" in catalog.text and "/auto/vykup/moskvich-3" in catalog.text
    assert catalog.headers["x-robots-tag"] == "noindex"  # the demo's offers stay out of search results
    first = re.search(r'href="(/auto/tp-\d{4}-[a-z0-9-]+)"', catalog.text).group(1)
    page = c.get(first)
    assert page.status_code == 200 and "application/ld+json" in page.text and "Итого" in page.text
    # A car's address without the model, or with a wrong one, redirects to the canonical address.
    code = first.split("/")[-1][:7]
    moved = c.get(f"/auto/{code}", follow_redirects=False)
    assert moved.status_code == 301 and moved.headers["location"] == first
    assert c.get("/auto/tp-9999").status_code == 404
    premium = c.get("/auto", params={"cls": "Премиум"}).text
    assert "Mercedes-Benz E 200" in premium and "Haval Jolion" not in premium


def test_buyout_schedule_changes_the_sum():
    a = site.buyout_offer("haval-f7", "7/0")
    b = site.buyout_offer("haval-f7", "5/2")
    assert a["days"] > b["days"] and a["total"] > b["total"] and a["final"] == b["final"]
    assert client().get("/auto/vykup/haval-f7?schedule=5/2").status_code == 200
    assert client().get("/auto/vykup/unknown").status_code == 404


def test_request_lands_in_the_visitors_bitrix24():
    c = client()
    catalog = c.get("/auto").text
    first = re.search(r'href="(/auto/tp-\d{4}-[a-z0-9-]+)"', catalog).group(1)
    page = c.get(first).text
    form = dict(re.findall(r'<input type="hidden" name="(\w+)" value="([^"]*)"', page))
    sent = c.post(
        "/auto/request",
        data={**form, "name": "Тест Сайтов", "comment": "детское кресло"},
        headers={"Origin": URL},
        follow_redirects=False,
    )
    assert sent.status_code == 303 and sent.headers["location"].startswith("/auto/sent?lead=")
    assert c.cookies.get("fleet_session")  # the request opened a demo space for this visitor
    lead = int(re.search(r"lead=(\d+)", sent.headers["location"]).group(1))
    deal = int(re.search(r"deal=(\d+)", sent.headers["location"]).group(1))
    key = c.post("/api/v1/b24app/session").json()["key"]
    leads = c.post(f"/api/b24/rest/{key}/crm.lead.list.json", json={"filter": {"ID": str(lead)}}).json()["result"]
    assert leads and leads[0]["SOURCE_ID"] == "WEB" and leads[0]["NAME"] == "Тест"
    deals = c.post(f"/api/b24/rest/{key}/crm.deal.get.json", json={"id": deal}).json()["result"]
    assert deals["CATEGORY_ID"] == "0" and deals["STAGE_ID"] == "NEW" and float(deals["OPPORTUNITY"]) > 0
    crm = c.get("/api/v1/crm").json()  # the cabinet's snapshot already has it
    assert any(x["id"] == str(lead) for x in crm["leads"])
    assert "Спасибо" in c.get(sent.headers["location"]).text
    c.post("/api/v1/session/role", json={"role": "driver"})
    opened = c.post("/auto/cabinet", headers={"Origin": URL}, follow_redirects=False)
    assert opened.headers["location"] == "/#app/crm" and c.get("/api/v1/session").json()["role"] == "manager"
    with db() as s:
        sid = s.scalar(
            select(Space.id).where(Space.token == hashlib.sha256(c.cookies["fleet_session"].encode()).hexdigest())
        )
    drop_space(sid)


def test_crawler_files():
    c = client()
    robots = c.get("/robots.txt").text
    assert "Disallow: /" in robots and "Sitemap:" in robots
    sitemap = c.get("/sitemap.xml")
    assert sitemap.headers["content-type"].startswith("application/xml")
    assert sitemap.text.count("<url>") >= 50 and "/auto/vykup/haval-f7" in sitemap.text
