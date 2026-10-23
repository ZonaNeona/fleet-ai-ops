"""Bitrix24 local application around the fleet: the PHP app (b24app/) talks to a portal over REST, and the fleet
plays both roles the app needs — the portal (the emulated one, served over HTTP in the inbound-webhook format)
and the fleet's own API that the app's widget and robot ask about a driver.

    portal (emulator)  ←REST─  b24app/ (PHP 8: placement, robot, events; Vue 3 widget)  ─HTTP→  fleet API

A visitor gets an app key bound to their demo space; it is the webhook secret of the emulated portal and the
credential of the app towards the fleet. The «Запустить робота» button sends the PHP handler exactly the form a
portal sends a robot, so the handler cannot tell the emulator from a real Bitrix24.
"""

import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from .db import URL, Item, Space, System, db, now
from .domain import fail

router = APIRouter()
VIEW = {"owner", "admin", "manager", "finance"}
ROBOT_CODE = "fleet_driver_check"


def app_url():
    return os.getenv("B24APP_URL", URL + "/b24app").rstrip("/")


def rest_base(key):
    """Where the app reaches the emulated portal; inside docker compose this is the web container."""
    return os.getenv("B24_EMULATOR_URL", URL).rstrip("/") + f"/api/b24/rest/{key}/"


# ---------------------------------------------------------------- keys


def issue_key(s, sp):
    key = "b24_" + secrets.token_urlsafe(18)
    s.add(System(key="b24key:" + hashlib.sha256(key.encode()).hexdigest()[:40],
                 data={"space": sp.id, "expires": (now() + timedelta(hours=24)).isoformat()}))
    return key


def space_of(key):
    if not key or len(key) > 80:
        return None
    with db() as s:
        row = s.get(System, "b24key:" + hashlib.sha256(key.encode()).hexdigest()[:40])
        sp = s.get(Space, row.data["space"]) if row and row.data["expires"] >= now().isoformat() else None
        if sp:
            sp.touched = now()
        return sp.id if sp else None


def portal_call(space_id, method, params, source):
    from .crm import Emulator, ReadOnly, portal

    with db() as s:
        sp = s.get(Space, space_id)
        _, item = portal(s, sp)
        s.refresh(item, with_for_update=True)
        holder = {}

        def save(data):
            holder["data"] = data

        try:
            answer = Emulator(json.loads(json.dumps(item.data)), save).call(method, params, source=source)
        except ReadOnly as e:
            return JSONResponse({"error": "ERROR_METHOD_NOT_FOUND" if "не разрешён" in str(e) else "INVALID_ARG_VALUE",
                                 "error_description": str(e)}, status_code=400)
        if "data" in holder:
            item.data = holder["data"]
            item.version += 1
        return answer


# ---------------------------------------------------------------- the emulated portal over HTTP


def form_params(raw):
    """PHP-style form arrays (fields[TITLE]=…) → nested dict, as a portal accepts them."""
    out = {}
    for key, values in parse_qs(raw, keep_blank_values=True).items():
        parts = key.replace("]", "").split("[")
        node = out
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = values[-1]
    return out


@router.api_route("/api/b24/rest/{key}/{method}", methods=["GET", "POST"])
async def rest(key: str, method: str, request: Request):
    space = space_of(key)
    if not space:
        return JSONResponse({"error": "INVALID_CREDENTIALS", "error_description": "Неверный или истёкший ключ"},
                            status_code=401)
    method = method.removesuffix(".json")
    body = await request.body()
    if request.headers.get("content-type", "").startswith("application/json") and body:
        params = json.loads(body)
    else:
        params = form_params(body.decode() if body else request.url.query)
    params.pop("auth", None)
    import anyio

    return await anyio.to_thread.run_sync(portal_call, space, method, params, "приложение")


# ---------------------------------------------------------------- what the app asks the fleet about


def deal_of(s, space_id, deal_id):
    from .crm import portal

    sp = s.get(Space, space_id)
    transport, _ = portal(s, sp)
    deal = next((d for d in transport.data["deals"] if d["ID"] == str(deal_id)), None)
    if not deal:
        fail("Сделка не найдена", 404)
    return sp, deal


def card(s, sp, deal):
    from .miniapp import balance

    out = {"deal": {"id": deal["ID"], "title": deal["TITLE"], "stage": deal["STAGE_ID"], "funnel": deal["CATEGORY_ID"]}}
    if deal["CATEGORY_ID"] == "1":
        out["candidate"] = {"name": deal["TITLE"].split("·")[-1].strip(), "experience": deal.get("UF_CRM_EXPERIENCE")}
        return out
    c = s.scalar(select(Item).where(Item.space == sp.id, Item.kind == "contract", Item.code == deal.get("UF_CRM_CONTRACT")))
    if not c:
        out["note"] = "Договора по сделке ещё нет: машина не выдана"
        return out
    car = s.get(Item, c.data["vehicle"])
    person = s.get(Item, c.data["client"])
    scope = SimpleNamespace(id=sp.id)
    charged = Decimal(balance(s, scope, c.id, ["charge"]))
    paid = Decimal(balance(s, scope, c.id, ["payment"]))
    fines = [x for x in s.scalars(select(Item).where(Item.space == sp.id, Item.kind == "source_record",
                                                       Item.data["source"].astext == "fines",
                                                       Item.data["vehicle"].astext == car.id))]
    docs = [x for x in s.scalars(select(Item).where(Item.space == sp.id, Item.kind == "inbox"))
            if (x.data.get("links") or {}).get("vehicle") == car.id]
    out.update({
        "driver": {"name": person.data.get("name") if person else "—", "phone": person.data.get("phone") if person else None},
        "contract": {"code": c.code, "status": c.data["status"], "start": c.data["start"], "end": c.data["end"],
                     "rate": c.data["rate"], "direction": c.data["direction"]},
        "car": {"code": car.code, "model": car.data["model"], "plate": car.data["plate"], "status": car.data["status"],
                "image": car.data.get("thumb")},
        "money": {"charged": f"{charged:.2f}", "paid": f"{paid:.2f}", "debt": f"{max(charged - paid, Decimal(0)):.2f}",
                  "crm_paid": deal.get("UF_CRM_PAID")},
        "fines": [{"number": (x.data.get("values") or {}).get("external_id"), "amount": (x.data.get("values") or {}).get("fine")}
                  for x in fines],
        "documents": [{"code": x.code, "kind": x.data.get("kind"), "status": x.data.get("status")} for x in docs],
    })
    return out


def rub(v):
    return f"{Decimal(v):,.0f}".replace(",", " ") + " ₽"


def verdict(info):
    """The robot «Проверить водителя»: rules, not a model — the result goes back into the deal."""
    reasons = []
    if "candidate" in info:
        exp = int(info["candidate"].get("experience") or 0)
        if exp < 3:
            reasons.append(f"стаж {exp} г. — меньше 3 лет")
        return {"ok": not reasons, "reasons": reasons or ["стаж от 3 лет"], "kind": "candidate"}
    if "money" not in info:
        return {"ok": True, "reasons": [info.get("note", "проверять нечего")], "kind": "none"}
    debt = Decimal(info["money"]["debt"])
    if debt > 0:
        reasons.append(f"долг {rub(debt)}")
    crm_paid, ledger = Decimal(info["money"]["crm_paid"] or 0), Decimal(info["money"]["paid"])
    if crm_paid > ledger:
        reasons.append(f"в CRM отмечено на {rub(crm_paid - ledger)} больше, чем пришло денег")
    if info["fines"]:
        reasons.append(f"штрафов: {len(info['fines'])}")
    waiting = [d for d in info["documents"] if d["status"] in ("review", "mismatch")]
    if waiting:
        reasons.append(f"документов ждут решения: {len(waiting)}")
    return {"ok": not reasons, "reasons": reasons or ["долгов, штрафов и расхождений нет"], "kind": "driver"}


def guard(request: Request):
    space = space_of(request.query_params.get("key") or request.headers.get("x-b24app-key"))
    if not space:
        fail("Нужен ключ приложения", 401)
    return space


@router.get("/api/b24app/deal/{deal_id}")
def app_deal(deal_id: str, request: Request):
    space = guard(request)
    with db() as s:
        sp, deal = deal_of(s, space, deal_id)
        info = card(s, sp, deal)
        return {**info, "verdict": verdict(info)}


# ---------------------------------------------------------------- the cabinet side


def viewer(s, request):
    from .api import auth

    sp = auth(s, request)
    if sp.role not in VIEW:
        fail("Приложение Битрикс24 показывается собственнику, менеджеру и финансисту", 403)
    return sp


def key_for(s, sp):
    """One app key per visitor space, reused while valid. Checked inside the caller's transaction: the space row
    is already locked there, and a second connection touching it would wait for this one forever."""
    current = sp.data.get("b24app_key")
    if current:
        row = s.get(System, "b24key:" + hashlib.sha256(current.encode()).hexdigest()[:40])
        if row and row.data["space"] == sp.id and row.data["expires"] >= now().isoformat():
            return current
    key = issue_key(s, sp)
    sp.data = {**sp.data, "b24app_key": key}
    return key


@router.post("/api/v1/b24app/session")
def app_session(request: Request):
    with db() as s:
        sp = viewer(s, request)
        key = key_for(s, sp)
        return {"key": key, "widget": "/b24app/index.php", "rest": rest_base(key), "robot": ROBOT_CODE}


@router.get("/api/v1/b24app/journal")
def app_journal(request: Request, deal: str):
    from .crm import portal

    with db() as s:
        sp = viewer(s, request)
        transport, _ = portal(s, sp)
        d = transport.data
        return {
            "comments": [c for c in d.get("comments", []) if c["ENTITY_ID"] == str(deal)][-20:],
            "tasks": [x for x in d.get("tasks", []) if f"D_{deal}" in (x.get("UF_CRM_TASK") or [])][-10:],
            "events": d.get("events", [])[-10:],
            "log": d.get("log", [])[-30:],
            "deal": next((x for x in d["deals"] if x["ID"] == str(deal)), None),
        }


@router.post("/api/v1/b24app/robot")
def app_robot(body: dict, request: Request):
    """Plays the portal: sends the PHP handler the form Bitrix24 sends when a business process reaches the robot."""
    deal = str(body.get("deal") or "")
    with db() as s:
        sp = viewer(s, request)
        deal_of(s, sp.id, deal)
        key = key_for(s, sp)
    token = "evt_" + secrets.token_hex(8)
    form = {
        "event_token": token,
        "code": ROBOT_CODE,
        "document_id[0]": "crm", "document_id[1]": "CCrmDocumentDeal", "document_id[2]": f"DEAL_{deal}",
        "document_type[0]": "crm", "document_type[1]": "CCrmDocumentDeal", "document_type[2]": "DEAL",
        "properties[notify_manager]": "Y",
        "auth[access_token]": key, "auth[domain]": "fleet-demo.bitrix24.ru",
        "auth[client_endpoint]": rest_base(key), "auth[application_token]": app_token(key),
        "ts": str(int(datetime.now().timestamp())),
    }
    try:
        r = httpx.post(app_url() + "/robot.php", data=form, timeout=40)
    except httpx.HTTPError as e:
        fail(f"Приложение не ответило: {type(e).__name__}", 502)
    if r.status_code != 200:
        fail(f"Приложение ответило {r.status_code}: {r.text[:200]}", 502)
    return {"event_token": token, "app": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:300]}


def app_token(key):
    """What a portal would send as application_token: the app checks it before trusting a robot call."""
    return hashlib.sha256(("app:" + key).encode()).hexdigest()[:32]


@router.get("/api/b24app/app-token")
def app_token_check(request: Request):
    """The PHP app verifies a robot call by asking the fleet for the token that belongs to the key."""
    guard(request)
    return {"application_token": app_token(request.query_params.get("key") or request.headers.get("x-b24app-key") or "")}

