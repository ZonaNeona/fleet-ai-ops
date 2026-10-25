"""The fleet's client site «Аренда и выкуп авто»: server-rendered pages (FastAPI + Jinja), not part of the SPA.

    /auto                          catalog: rental cars and buyout models, filters in the query string
    /auto/<code>-<model>           a rental car: photo, terms, 5-week availability, price calculator, request form
    /auto/vykup/<model>            a buyout offer: payment schedule and a request form
    POST /auto/request             request → lead + deal in the «Прокат» funnel of the visitor's Bitrix24 → cabinet
    /sitemap.xml, /robots.txt

The catalog comes from one shared showcase space, so every visitor and crawler sees the same site; a request lands in
the visitor's own demo space (opened on the spot if there is none), where the manager sees it in the cabinet. Prices
are computed by the same server function as in the cabinet and the Mini App. The demo is closed to indexing unless
SITE_INDEX=1: the SEO mechanics are real, the offers are not.
"""

import json
import os
import re
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select, text

from .db import URL, Booking, Item, Space, System, db, now
from .domain import audit, today
from .seed import FLEET, claim_space

router = APIRouter()
MSK = ZoneInfo("Europe/Moscow")
TEMPLATES = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(),
    trim_blocks=True,
    lstrip_blocks=True,
)
BUYOUT = ["moskvich-3", "belgee-x50", "geely-emgrand", "haval-f7"]  # the models the fleet sells on buyout
BUYOUT_FINAL = Decimal(150000)  # the final payment of a buyout contract, as in the fleet's own contracts
SCHEDULES = {"7/0": "без выходных", "6/1": "один выходной в неделю", "5/2": "два выходных в неделю"}
CLASSES = ["Комфорт", "Бизнес", "Премиум"]
MONTHS = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]
WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def rub(v) -> str:
    return f"{Decimal(v):,.0f}".replace(",", " ") + " ₽"


def day(d) -> str:
    return f"{d.day} {MONTHS[d.month - 1]}"


TEMPLATES.filters["rub"] = rub
TEMPLATES.filters["day"] = day


def page(name, request: Request, status=200, **ctx):
    index = os.getenv("SITE_INDEX") == "1"
    html = TEMPLATES.get_template(name).render(url=URL, path=request.url.path, index=index, **ctx)
    r = HTMLResponse(html, status_code=status)
    if not index:
        r.headers["X-Robots-Tag"] = "noindex"
    return r


# ---------------------------------------------------------------- the showcase every visitor sees


def showcase(s) -> Space:
    """One shared space behind the site. It lives like any demo space; when it expires, the next visit takes a new one
    from the pool: the seed is deterministic, so car codes and URLs stay the same."""
    row = s.get(System, "site_space")
    sp = s.get(Space, row.data["id"]) if row else None
    if sp is None:
        s.execute(text("SELECT pg_advisory_xact_lock(684412)"))
        row = s.get(System, "site_space")
        sp = s.get(Space, row.data["id"]) if row else None
    if sp is None:
        sp = claim_space(s)
        sp.role = "owner"
        sp.data = {**sp.data, "site": True}
        if row:
            row.data = {"id": sp.id}
        else:
            s.add(System(key="site_space", data={"id": sp.id}))
        s.flush()
    elif sp.touched < now() - timedelta(hours=6):
        sp.touched = now()
    return sp


def slug(model: str) -> str:
    return next((k for k, c in FLEET.items() if c["model"] == model), re.sub(r"[^a-z0-9]+", "-", model.lower()))


def busy(s, sp) -> dict[str, list[tuple[datetime, datetime]]]:
    rows = s.execute(
        select(Booking.vehicle, Booking.period).where(
            Booking.space == sp.id,
            Booking.state.in_(["active", "confirmed", "hold"]),
            (Booking.expires.is_(None)) | (Booking.expires > now()),
        )
    ).all()
    out: dict[str, list] = {}
    for vehicle, period in rows:
        if period.upper and period.upper > now():
            out.setdefault(vehicle, []).append((period.lower, period.upper))
    return out


def free_from(periods) -> datetime | None:
    """When the car is next free: the end of the chain of bookings that covers now."""
    moment = now()
    for start, end in sorted(periods):
        if start <= moment < end:
            moment = end
    return moment if moment > now() else None


def car(v, periods):
    c = FLEET.get(slug(v.data["model"]), {})
    free = free_from(periods)
    return {
        "id": v.id,
        "code": v.code,
        "model": v.data["model"],
        "slug": slug(v.data["model"]),
        "url": f"/auto/{v.code.lower()}-{slug(v.data['model'])}",
        "class": v.data.get("class", c.get("class", "")),
        "year": v.data["year"],
        "rate": Decimal(v.data["rate"]),
        "image": v.data.get("image"),
        "thumb": v.data.get("thumb"),
        "mileage": v.data.get("mileage"),
        "free": free.astimezone(MSK).date() if free else None,
    }


def rental_cars(s, sp):
    cars = s.scalars(
        select(Item)
        .where(Item.space == sp.id, Item.kind == "vehicle", Item.data["direction"].astext == "rental")
        .order_by(Item.code)
    ).all()
    periods = busy(s, sp)
    return [car(v, periods.get(v.id, [])) for v in cars]


def buyout_offer(key, schedule="6/1"):
    c = FLEET[key]
    daily = Decimal(c["rate"] + 200)  # buyout rate: the taxi rate plus the share that goes to the car's price
    start = today()
    end = start.replace(year=start.year + 1)
    days = sum(
        1
        for i in range((end - start).days)
        if not (
            (schedule == "6/1" and (start + timedelta(i)).weekday() == 6)
            or (schedule == "5/2" and (start + timedelta(i)).weekday() >= 5)
        )
    )
    return {
        "slug": key,
        "model": c["model"],
        "class": c["class"],
        "url": f"/auto/vykup/{key}",
        "image": f"/cars/{key}.webp",
        "thumb": f"/cars/{key}-sm.webp",
        "daily": daily,
        "schedule": schedule,
        "days": days,
        "months": 12,
        "final": BUYOUT_FINAL,
        "total": daily * days + BUYOUT_FINAL,
        "month_payment": (daily * days / 12).quantize(Decimal(1)),
    }


def calendar(periods, weeks=5):
    start = today() - timedelta(days=today().weekday())
    out = []
    for i in range(weeks * 7):
        d = start + timedelta(days=i)
        moment = datetime(d.year, d.month, d.day, 10, tzinfo=MSK)  # a rental day runs 10:00 → 10:00 MSK
        out.append(
            {"date": d, "past": d < today(), "busy": any(a <= moment < b for a, b in periods), "today": d == today()}
        )
    return out


# ---------------------------------------------------------------- pages


@router.get("/auto", response_class=HTMLResponse)
def catalog(request: Request, type: str = "", cls: str = "", price: int = 0, sort: str = "price", free: str = ""):
    with db() as s:
        sp = showcase(s)
        cars = rental_cars(s, sp)
    if cls:
        cars = [c for c in cars if c["class"] == cls]
    if price:
        cars = [c for c in cars if c["rate"] <= price]
    if free:
        cars = [c for c in cars if not c["free"] or c["free"] <= today() + timedelta(days=3)]
    cars.sort(
        key=lambda c: (c["free"] or today(), c["rate"]) if sort == "free" else (c["rate"], c["code"]),
        reverse=sort == "price_desc",
    )
    offers = [buyout_offer(k) for k in BUYOUT]
    # One card per model and the earliest free car: the catalog stays readable on a phone.
    models: dict[str, dict] = {}
    for c in cars:
        m = models.setdefault(c["model"], {**c, "count": 0, "cars": []})
        m["count"] += 1
        m["cars"].append(c)
        if (c["free"] or today()) < (m["free"] or today()):
            m.update({k: c[k] for k in ("code", "url", "free")})
    return page(
        "catalog.html",
        request,
        cars=cars,
        models=list(models.values()),
        offers=offers,
        type=type,
        cls=cls,
        price=price,
        sort=sort,
        free=free,
        classes=CLASSES,
        total=len(cars),
    )


# Declared before /auto/{ref}: routes match in order.
@router.get("/auto/sent", response_class=HTMLResponse)
def sent(request: Request, lead: int = 0, deal: int = 0, title: str = ""):
    return page("sent.html", request, lead=lead, deal=deal, title=title[:120])


@router.get("/auto/vykup/{key}", response_class=HTMLResponse)
def buyout_page(key: str, request: Request, schedule: str = "6/1"):
    if key not in BUYOUT:
        return page("missing.html", request, status=404)
    offer = buyout_offer(key, schedule if schedule in SCHEDULES else "6/1")
    others = [buyout_offer(k) for k in BUYOUT if k != key]
    return page("buyout.html", request, offer=offer, schedules=SCHEDULES, others=others)


@router.get("/auto/{ref}", response_class=HTMLResponse)
def car_page(
    ref: str,
    request: Request,
    start: str = "",
    end: str = "",
    delivery: str = "",
    collection: str = "",
    driver: str = "",
    error: str = "",
):
    from .miniapp import rental_quote

    m = re.match(r"^(tp-\d{4})(?:-[a-z0-9-]+)?$", ref)
    if not m:
        return page("missing.html", request, status=404)
    with db() as s:
        sp = showcase(s)
        v = s.scalar(
            select(Item).where(
                Item.space == sp.id,
                Item.kind == "vehicle",
                Item.code == m.group(1).upper(),
                Item.data["direction"].astext == "rental",
            )
        )
        if not v:
            return page("missing.html", request, status=404)
        periods = busy(s, sp).get(v.id, [])
        c = car(v, periods)
        if ref != c["url"].rsplit("/", 1)[1]:
            return RedirectResponse(c["url"] + (f"?{request.url.query}" if request.url.query else ""), 301)
        first = c["free"] if c["free"] and c["free"] > today() else today() + timedelta(days=1)
        start = start or str(first)
        end = end or str(datetime.fromisoformat(start).date() + timedelta(days=3)) if start else ""
        quote = None
        error = "Проверьте даты: начало не раньше сегодня, окончание позже начала." if error else ""
        try:
            quote = rental_quote(
                s,
                sp,
                {
                    "vehicle": v.id,
                    "start": start,
                    "end": end,
                    "delivery": bool(delivery),
                    "collection": bool(collection),
                    "additional_driver": driver[:60],
                },
            )
            wanted = (
                datetime.fromisoformat(start + "T10:00:00+03:00"),
                datetime.fromisoformat(end + "T10:00:00+03:00"),
            )
            if any(a < wanted[1] and wanted[0] < b for a, b in periods):
                error = "На эти даты машина занята — посмотрите календарь или выберите другую машину этой модели."
        except HTTPException as e:
            error = str(e.detail)
        except ValueError:
            error = "Проверьте даты"
        same = [x for x in rental_cars(s, sp) if x["model"] == c["model"] and x["code"] != c["code"]][:6]
    return page(
        "car.html",
        request,
        car=c,
        quote=quote,
        error=error,
        start=start,
        end=end,
        delivery=bool(delivery),
        collection=bool(collection),
        driver=driver,
        calendar=calendar(periods),
        weekdays=WEEKDAYS,
        same=same,
    )


# ---------------------------------------------------------------- the request: lead + deal in the visitor's Bitrix24


def portal_write(s, sp, method, fields):
    from .crm import Emulator, portal

    transport, item = portal(s, sp)
    if item is None:  # a live portal: Live.call refuses writes unless BITRIX24_WRITE=1
        return transport.call(method, {"fields": fields})["result"]
    s.refresh(item, with_for_update=True)
    emulator = Emulator(json.loads(json.dumps(item.data)))
    answer = emulator.call(method, {"fields": fields}, source="сайт")["result"]
    item.data = emulator.data
    item.version += 1
    return answer


@router.post("/auto/request")
def request_car(
    request: Request,
    kind: str = Form(...),
    ref: str = Form(...),
    name: str = Form(""),
    phone: str = Form(""),
    start: str = Form(""),
    end: str = Form(""),
    schedule: str = Form("6/1"),
    comment: str = Form(""),
    delivery: str = Form(""),
    collection: str = Form(""),
    driver: str = Form(""),
):
    from .api import auth, open_session
    from .crm import sync

    name = re.sub(r"\s+", " ", name).strip()[:60] or "Гость сайта"
    phone = re.sub(r"[^\d+()\- ]", "", phone)[:20]
    response = RedirectResponse("/auto/sent", 303)
    with db() as s:
        site = showcase(s)
        if kind == "rental":
            v = s.scalar(select(Item).where(Item.space == site.id, Item.kind == "vehicle", Item.code == ref.upper()))
            if not v:
                return page("missing.html", request, status=404)
            from .miniapp import rental_quote

            try:
                quote = rental_quote(
                    s,
                    site,
                    {
                        "vehicle": v.id,
                        "start": start,
                        "end": end,
                        "delivery": bool(delivery),
                        "collection": bool(collection),
                        "additional_driver": driver[:60],
                    },
                )
            except (HTTPException, ValueError):
                return RedirectResponse(car(v, [])["url"] + "?error=dates", 303)
            title = (
                f"Сайт · прокат · {v.data['model']} · {quote['days']} дн. с {day(datetime.fromisoformat(start).date())}"
            )
            amount, plate = Decimal(quote["total"]), v.data["plate"]
        elif kind == "buyout" and ref in BUYOUT:
            offer = buyout_offer(ref, schedule if schedule in SCHEDULES else "6/1")
            title = f"Сайт · выкуп · {offer['model']} · график {offer['schedule']}"
            amount, plate = offer["total"], ""
        else:
            return page("missing.html", request, status=404)
        try:
            sp = auth(s, request)
        except HTTPException:
            sp = open_session(
                s, request, response
            )  # the site works without the cabinet; the request opens a demo space
        first, _, last = name.partition(" ")
        lead = portal_write(
            s,
            sp,
            "crm.lead.add",
            {
                "TITLE": title,
                "NAME": first,
                "LAST_NAME": last,
                "SOURCE_ID": "WEB",
                "STATUS_ID": "NEW",
                "PHONE": [{"VALUE": phone, "VALUE_TYPE": "MOBILE"}] if phone else [],
                "COMMENTS": comment[:500],
            },
        )
        deal = portal_write(
            s,
            sp,
            "crm.deal.add",
            {
                "TITLE": title,
                "CATEGORY_ID": "0",
                "STAGE_ID": "NEW",
                "OPPORTUNITY": f"{amount:.2f}",
                "LEAD_ID": lead,
                "SOURCE_ID": "WEB",
                "UF_CRM_VEHICLE": plate,
            },
        )
        sync(s, sp)
        audit(s, sp, f"Заявка с сайта → лид #{lead} и сделка #{deal} в Битрикс24", None, via="site")
        response.headers["location"] = "/auto/sent?" + urlencode({"lead": lead, "deal": deal, "title": title[:120]})
        return response


@router.post("/auto/cabinet")
def cabinet(request: Request):
    """«Open in the cabinet»: the visitor sees their request as the rental manager does, whatever role they had."""
    from .api import auth

    with db() as s:
        try:
            auth(s, request).role = "manager"
        except HTTPException:
            pass
    return RedirectResponse("/#app/crm", 303)


# ---------------------------------------------------------------- crawlers


@router.get("/sitemap.xml")
def sitemap():
    with db() as s:
        cars = rental_cars(s, showcase(s))
    urls = ["/auto"] + [c["url"] for c in cars] + [f"/auto/vykup/{k}" for k in BUYOUT]
    body = "".join(f"<url><loc>{URL}{u}</loc><lastmod>{today()}</lastmod></url>" for u in urls)
    return Response(
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>',
        media_type="application/xml",
    )


@router.get("/robots.txt")
def robots():
    if os.getenv("SITE_INDEX") == "1":
        rules = "User-agent: *\nAllow: /auto\nDisallow: /api/\n"
    else:  # a demo with made-up offers stays out of search results
        rules = "User-agent: *\nDisallow: /\n"
    return Response(rules + f"Sitemap: {URL}/sitemap.xml\n", media_type="text/plain")
