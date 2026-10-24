"""Online payments: YooKassa (a test shop by keys, the emulator otherwise) and Telegram Payments (by provider token).

The amount is always computed by the server (`miniapp.payment_terms`), never taken from the client. A provider
notification is never trusted as it arrives: the handler re-reads the payment from the provider, checks the amount
and our id in its metadata, and posts to the ledger once — the provider's id is the ledger key, so a repeated
notification changes nothing. A refund posts a reversal under the refund's own id.
"""

import html
import os
import uuid
from datetime import timedelta
from decimal import Decimal

import httpx
from fastapi import APIRouter, Body, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from .db import URL, Entry, Item, Space, System, db, now
from .domain import audit, fail, get, money, post, update

router = APIRouter()
STAFF = {"owner", "admin", "finance"}
TG_API = "https://api.telegram.org/bot{token}/{method}"


class ProviderError(RuntimeError):
    pass


def amount_of(value) -> dict:
    return {"value": f"{money(value):.2f}", "currency": "RUB"}


# ---------------------------------------------------------------- YooKassa: the real API and its emulator


class YooKassa:
    """API v3: Basic auth shopId:secret, an Idempotence-Key on every write, notifications without a signature."""

    mode = "live"
    base = "https://api.yookassa.ru/v3/"

    def __init__(self, shop, secret):
        self.auth = (shop, secret)

    def _send(self, method, path, body=None, idem=None):
        headers = {"Idempotence-Key": idem} if idem else {}
        try:
            r = httpx.request(method, self.base + path, auth=self.auth, json=body, headers=headers, timeout=20)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            raise ProviderError("ЮKassa недоступна или отклонила запрос") from None

    def create(self, amount, description, metadata, return_url, idem):
        return self._send("POST", "payments", {
            "amount": amount_of(amount), "capture": True, "description": description[:128], "metadata": metadata,
            "confirmation": {"type": "redirect", "return_url": return_url}}, idem)

    def payment(self, pid):
        return self._send("GET", "payments/" + pid)

    def refund(self, pid, amount, idem):
        return self._send("POST", "refunds", {"payment_id": pid, "amount": amount_of(amount)}, idem)

    def get_refund(self, rid):
        return self._send("GET", "refunds/" + rid)


class Emulator:
    """A test shop that answers in the API's shapes. Its own state lives apart from the stand's data, as a real
    provider's would; paying on its checkout page sends the notification to the same handler as YooKassa's."""

    mode = "emulator"

    def __init__(self, s):
        self.s = s

    def _row(self, key):
        return self.s.get(System, "ykemu:" + key)

    def _save(self, key, data):
        row = self._row(key)
        if row:
            row.data = data
        else:
            self.s.add(System(key="ykemu:" + key, data=data))
        self.s.flush()
        return data

    def create(self, amount, description, metadata, return_url, idem):
        seen = self._row("idem:" + idem)
        if seen:  # the same Idempotence-Key returns the same object, as the API does for 24 hours
            return self._row(seen.data["id"]).data
        pid = str(uuid.uuid4())
        obj = {"id": pid, "status": "pending", "paid": False, "amount": amount_of(amount), "description": description,
               "metadata": metadata, "created_at": now().isoformat(), "test": True,
               "confirmation": {"type": "redirect", "return_url": return_url,
                                "confirmation_url": f"{URL}/api/pay/yookassa/checkout/{pid}"}}
        self._save("idem:" + idem, {"id": pid, "at": now().isoformat()})
        return self._save(pid, obj)

    def payment(self, pid):
        row = self._row(pid)
        if not row:
            raise ProviderError("Платёж не найден")
        return row.data

    def settle(self, pid, paid):
        obj = dict(self.payment(pid))
        if obj["status"] == "pending":
            obj.update(status="succeeded" if paid else "canceled", paid=paid, captured_at=now().isoformat(),
                       payment_method={"type": "bank_card", "card": {"last4": "4477", "card_type": "MasterCard"}} if paid else None)
            self._save(pid, obj)
        return obj

    def refund(self, pid, amount, idem):
        seen = self._row("idem:" + idem)
        if seen:
            return self._row(seen.data["id"]).data
        obj = self.payment(pid)
        if obj["status"] != "succeeded":
            raise ProviderError("Возврат возможен только по успешному платежу")
        rid = str(uuid.uuid4())
        refund = {"id": rid, "payment_id": pid, "status": "succeeded", "amount": amount_of(amount), "created_at": now().isoformat()}
        self._save("idem:" + idem, {"id": rid, "at": now().isoformat()})
        return self._save(rid, refund)

    def get_refund(self, rid):
        return self.payment(rid)


def provider(s):
    shop, secret = os.getenv("YOOKASSA_SHOP_ID"), os.getenv("YOOKASSA_SECRET_KEY")
    return YooKassa(shop, secret) if shop and secret else Emulator(s)


def trail(x, step, **data):
    """The payment's own journal: what we asked, what came back, what was posted, what was ignored."""
    log = list(x.data.get("log", []))[-30:]
    log.append({"at": now().isoformat(timespec="seconds"), "step": step, **data})
    update(x, log=log)


def mine(s, sp, pid):
    x = get(s, sp, pid, "demo_payment")
    if x.data.get("client") != sp.data.get(sp.role):
        fail("Платёж не найден", 404)
    return x


def safe_back(back):
    return back if isinstance(back, str) and back.startswith("/") and not back.startswith("//") and len(back) < 300 else "/?tg=1#tg/profile"


# ---------------------------------------------------------------- checkout from the Mini App


@router.post("/api/v1/payments/{pid}/yookassa")
def checkout(pid: str, request: Request, body: dict = Body(default={})):
    from .api import auth
    from .miniapp import payment_terms

    with db() as s:
        sp = auth(s, request)
        x = mine(s, sp, pid)
        s.refresh(x, with_for_update=True)
        if x.data["status"] != "pending":
            fail("Платёж уже завершён", 409)
        terms = payment_terms(s, sp, x.data["purpose"], x.data["target"])
        if terms["amount"] != x.data["amount"]:
            fail("Сумма изменилась. Получите новый расчёт.", 409)
        yk = provider(s)
        try:
            obj = yk.create(x.data["amount"], x.data["label"], {"payment": x.id, "space": sp.id},
                            URL + safe_back(body.get("back")), idem="fleet-" + x.id)
        except ProviderError as e:
            fail(str(e), 502)
        link = s.get(System, "pay:yookassa:" + obj["id"])
        if not link:
            s.add(System(key="pay:yookassa:" + obj["id"], data={"space": sp.id, "payment": x.id, "at": now().isoformat()}))
        update(x, provider={"name": "yookassa", "mode": yk.mode, "id": obj["id"]})
        trail(x, "Создан платёж в ЮKassa", request="POST /v3/payments", idempotence_key="fleet-" + x.id,
              status=obj["status"], mode=yk.mode)
        return {"confirmation_url": obj["confirmation"]["confirmation_url"], "mode": yk.mode, "provider_id": obj["id"]}


CHECKOUT = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Оплата · тестовый магазин</title><style>
body{{margin:0;font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#f2f3f5;color:#1d1f23;display:grid;place-items:center;min-height:100vh}}
main{{background:#fff;border-radius:18px;padding:28px 24px;width:min(380px,calc(100vw - 32px));box-sizing:border-box;box-shadow:0 8px 30px #0000000f}}
small{{color:#6b6f78}}.sum{{font-size:34px;font-weight:700;margin:10px 0 18px}}.card{{border:1px solid #e3e5e9;border-radius:12px;padding:12px 14px;margin:14px 0;font-family:ui-monospace,monospace}}
button{{width:100%;border:0;border-radius:12px;padding:14px;font:600 15px system-ui;margin-top:8px;cursor:pointer}}.pay{{background:#2d6cdf;color:#fff}}.no{{background:#eef0f3;color:#1d1f23}}
.tag{{display:inline-block;background:#fff4d6;color:#7a5600;border-radius:8px;padding:3px 8px;font-size:12px;font-weight:600}}
</style></head><body><main>
<span class="tag">ТЕСТОВЫЙ МАГАЗИН · ЭМУЛЯТОР ЮKASSA</span>
<p><small>{description}</small></p><div class="sum">{amount} ₽</div>
<div class="card">5555 5555 5555 4477<br><small>12/30 · CVC 000 · тестовая карта</small></div>
<form method="post"><input type="hidden" name="action" value="pay"><button class="pay">Оплатить</button></form>
<form method="post"><input type="hidden" name="action" value="cancel"><button class="no">Отказаться от оплаты</button></form>
<p><small>Деньги не списываются. После оплаты магазин пришлёт уведомление <code>payment.succeeded</code> — стенд перечитает платёж и проведёт его в учёт.</small></p>
</main></body></html>"""


@router.get("/api/pay/yookassa/checkout/{pid}", response_class=HTMLResponse)
def checkout_page(pid: str):
    with db() as s:
        try:
            obj = Emulator(s).payment(pid)
        except ProviderError:
            return HTMLResponse("Платёж не найден", 404)
        if obj["status"] != "pending":
            return RedirectResponse(obj["confirmation"]["return_url"], 303)
        value = Decimal(obj["amount"]["value"])
        return HTMLResponse(CHECKOUT.format(description=html.escape(obj["description"]),
                                           amount=f"{value:,.2f}".replace(",", " ").replace(".", ",")))


@router.post("/api/pay/yookassa/checkout/{pid}")
def checkout_submit(pid: str, action: str = Form("")):
    with db() as s:
        try:
            obj = Emulator(s).settle(pid, action == "pay")
        except ProviderError:
            return HTMLResponse("Платёж не найден", 404)
    # The shop notifies the stand the way YooKassa does: event + object, no signature.
    notify({"type": "notification", "event": "payment." + obj["status"], "object": obj})
    return RedirectResponse(obj["confirmation"]["return_url"], 303)


# ---------------------------------------------------------------- notifications: re-read, check, post once


@router.post("/api/pay/yookassa/webhook")
def webhook(body: dict = Body(...)):
    return notify(body)


def notify(body):
    event, obj = body.get("event", ""), body.get("object") or {}
    if not isinstance(obj, dict) or not isinstance(obj.get("id"), str) or len(obj["id"]) > 64:
        return {"ok": False}
    with db() as s:
        yk = provider(s)
        try:
            if event.startswith("refund."):
                fresh = yk.get_refund(obj["id"])
                pid = fresh.get("payment_id", "")
            else:
                fresh = yk.payment(obj["id"])
                pid = fresh["id"]
        except ProviderError:
            return {"ok": False}
        link = s.get(System, "pay:yookassa:" + pid)
        if not link:
            return {"ok": True, "ignored": "unknown payment"}
        sp, x = s.get(Space, link.data["space"]), s.get(Item, link.data["payment"])
        if not sp or not x:
            return {"ok": True, "ignored": "space expired"}
        s.refresh(x, with_for_update=True)
        heard = f"Уведомление {event} → перечитали {'возврат' if event.startswith('refund.') else 'платёж'}: {fresh['status']}"
        if event.startswith("refund."):
            return {"ok": True, **refunded(s, sp, x, fresh, heard)}
        if fresh["status"] == "canceled" and x.data["status"] == "pending":
            update(x, status="canceled")
            trail(x, heard, result="отменён плательщиком")
            return {"ok": True, "status": "canceled"}
        if fresh["status"] != "succeeded":
            trail(x, heard, result="ждём")
            return {"ok": True, "status": fresh["status"]}
        return {"ok": True, **settle(s, sp, x, "yookassa:" + pid, fresh["amount"]["value"],
                                    (fresh.get("metadata") or {}).get("payment"), heard)}


def settle(s, sp, x, key, value, meta_id, heard):
    if meta_id != x.id or money(value) != money(x.data["amount"]):
        trail(x, heard, result="отклонено: сумма или назначение не совпали")
        return {"status": "mismatch"}
    if x.data["status"] == "paid" or s.scalar(select(Entry.id).where(Entry.space == sp.id, Entry.key == key)):
        trail(x, heard, result="повтор — в учёт не проводим второй раз")
        return {"status": "duplicate"}
    post(s, sp, x.data["entry_kind"], money(value), x.data.get("vehicle"), x.data.get("contract"),
         x.data["label"].replace("Учебная оплата", "Оплата"), key=key, receipt=x.id, purpose=x.data["purpose"],
         provider=key.split(":")[0])
    update(x, status="paid", paid_at=now().isoformat())
    trail(x, heard, result=f"проведено в учёт, ключ {key}")
    audit(s, sp, "Онлайн-оплата проведена в учёт", x.id, amount=x.data["amount"])
    return {"status": "paid"}


def refunded(s, sp, x, fresh, heard):
    key = "yookassa-refund:" + fresh["id"]
    if fresh["status"] != "succeeded":
        trail(x, heard, result="возврат ещё не завершён")
        return {"status": fresh["status"]}
    if s.scalar(select(Entry.id).where(Entry.space == sp.id, Entry.key == key)):
        trail(x, heard, result="повтор возврата — пропущен")
        return {"status": "duplicate"}
    post(s, sp, x.data["entry_kind"], -money(fresh["amount"]["value"]), x.data.get("vehicle"), x.data.get("contract"),
         "Возврат онлайн-оплаты", key=key, receipt=x.id, purpose=x.data["purpose"], provider="yookassa")
    update(x, status="refunded", refunded_at=now().isoformat())
    trail(x, heard, result=f"сторно в учёте, ключ {key}")
    audit(s, sp, "Возврат онлайн-оплаты проведён", x.id, amount=fresh["amount"]["value"])
    return {"status": "refunded"}


@router.post("/api/v1/payments/{pid}/refund")
def refund(pid: str, request: Request):
    from .api import auth

    with db() as s:
        sp = auth(s, request)
        if sp.role not in STAFF:
            fail("Возврат делает собственник или финансист", 403)
        x = get(s, sp, pid, "demo_payment")
        s.refresh(x, with_for_update=True)
        prov = x.data.get("provider") or {}
        if x.data["status"] != "paid" or prov.get("name") != "yookassa":
            fail("Вернуть можно только проведённую онлайн-оплату ЮKassa", 409)
        yk = provider(s)
        try:
            obj = yk.refund(prov["id"], x.data["amount"], idem="fleet-refund-" + x.id)
        except ProviderError as e:
            fail(str(e), 502)
        trail(x, "Запрошен возврат", request="POST /v3/refunds", idempotence_key="fleet-refund-" + x.id, status=obj["status"])
    if yk.mode == "emulator":
        notify({"type": "notification", "event": "refund.succeeded", "object": {"id": obj["id"]}})
    return {"ok": True, "refund": obj["id"]}


# ---------------------------------------------------------------- Telegram Payments


def tg_token():
    return os.getenv("TELEGRAM_PAYMENT_TOKEN", "")


def tg_call(method, **params):
    r = httpx.post(TG_API.format(token=os.environ["TELEGRAM_BOT_TOKEN"], method=method), json=params, timeout=10)
    data = r.json()
    if not data.get("ok"):
        raise ProviderError(data.get("description") or "Telegram отклонил запрос")
    return data["result"]


@router.post("/api/v1/payments/{pid}/telegram")
def telegram_invoice(pid: str, request: Request):
    """An invoice link for Telegram.WebApp.openInvoice; the bot's test provider charges a test card."""
    from .api import auth

    if not tg_token() or not os.getenv("TELEGRAM_BOT_TOKEN"):
        fail("Платежи Telegram не подключены", 409)
    with db() as s:
        sp = auth(s, request)
        x = mine(s, sp, pid)
        if x.data["status"] != "pending":
            fail("Платёж уже завершён", 409)
        kopecks = int(money(x.data["amount"]) * 100)
        try:
            link = tg_call("createInvoiceLink", title=x.data["label"][:32], description=f"Квитанция {x.code}",
                           payload=x.id, provider_token=tg_token(), currency="RUB",
                           prices=[{"label": x.data["label"][:32], "amount": kopecks}])
        except (ProviderError, httpx.HTTPError) as e:
            fail(str(e) if isinstance(e, ProviderError) else "Telegram недоступен", 502)
        update(x, provider={"name": "telegram", "mode": "test"})
        trail(x, "Создан счёт Telegram", request="createInvoiceLink", amount_kopecks=kopecks)
        return {"link": link}


def telegram_update(data):
    """pre_checkout_query must be answered within 10 seconds; successful_payment posts to the ledger once."""
    q = data.get("pre_checkout_query")
    if q:
        with db() as s:
            x = s.get(Item, q.get("invoice_payload", ""))
            ok = bool(x and x.kind == "demo_payment" and x.data["status"] == "pending"
                      and int(money(x.data["amount"]) * 100) == q.get("total_amount") and q.get("currency") == "RUB")
            if x:
                trail(x, "pre_checkout_query", result="подтверждено" if ok else "отклонено")
        tg_call("answerPreCheckoutQuery", pre_checkout_query_id=q["id"], ok=ok,
                **({} if ok else {"error_message": "Сумма изменилась, откройте оплату заново"}))
        return {"pre_checkout": ok}
    paid = (data.get("message") or {}).get("successful_payment")
    if paid:
        with db() as s:
            x = s.get(Item, paid.get("invoice_payload", ""))
            if not x or x.kind != "demo_payment":
                return {"ignored": True}
            s.refresh(x, with_for_update=True)
            sp = s.get(Space, x.space)
            value = Decimal(paid["total_amount"]) / 100
            return settle(s, sp, x, "telegram:" + paid["telegram_payment_charge_id"], value, x.id, "successful_payment")
    return None


# ---------------------------------------------------------------- the console


@router.get("/api/v1/payments/config")
def config(request: Request):
    from .api import auth

    with db() as s:
        auth(s, request)
        return {"yookassa": provider(s).mode, "telegram": bool(tg_token() and os.getenv("TELEGRAM_BOT_TOKEN"))}


@router.get("/api/v1/payments")
def journal(request: Request):
    from .api import auth

    with db() as s:
        sp = auth(s, request)
        if sp.role not in STAFF:
            fail("Журнал платежей доступен собственнику и финансисту", 403)
        rows = s.scalars(select(Item).where(Item.space == sp.id, Item.kind == "demo_payment",
                                            Item.data["provider"].isnot(None)).order_by(Item.created.desc()).limit(30)).all()
        mode = provider(s).mode
        return {
            "mode": mode, "telegram": bool(tg_token()), "since": (now() - timedelta(days=1)).isoformat(),
            "payments": [{"id": x.id, "code": x.code, "label": x.data["label"], "amount": x.data["amount"],
                          "status": x.data["status"], "provider": x.data.get("provider"), "log": x.data.get("log", [])}
                         for x in rows],
            "webhook": URL + "/api/pay/yookassa/webhook",
        }
