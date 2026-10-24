"""VK and MAX bots on the Telegram bot's core: one scenario, three transports.

Inbound, each channel's event becomes the update shape `telegram.handle` already knows (message or callback with
a user and a chat); outbound, the core's messages — HTML text and inline buttons — become the channel's own API
call. Identity is per channel: a VK user is «vk:<id>», a MAX user «max:<id>», each with their own demo space.

    VK   Callback API  POST /api/v1/vk/callback     (VK_TOKEN, VK_SECRET, VK_CONFIRMATION)  → messages.send
    MAX  Bot API       POST /api/v1/max/webhook     (MAX_TOKEN, MAX_SECRET)                 → POST /messages

Events are deduplicated and handled by the worker, like Telegram's. Without tokens the bot emulator in the cabinet
shows, for every answer, the exact payload each channel would receive.
"""

import html
import json
import os
import re
import secrets

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from .db import Job, System, db, now

router = APIRouter()
VK_API = "https://api.vk.com/method/"
MAX_API = "https://platform-api.max.ru/"


def plain(text: str) -> str:
    """Telegram HTML → plain text for VK (it has no inline markup in bot messages)."""
    text = re.sub(r"<br\s*/?>", "\n", text or "")
    text = re.sub(r'<a href="([^"]+)">([^<]+)</a>', r"\2 (\1)", text)
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def buttons(m):
    """The core's inline keyboard as (text, kind, value) rows: kind is callback or link."""
    markup = m.get("kb")
    rows = []
    for row in (markup.inline_keyboard if markup else []):
        out = []
        for b in row:
            if b.callback_data:
                out.append((b.text, "callback", b.callback_data))
            elif b.web_app or b.url:
                out.append((b.text, "link", b.web_app.url if b.web_app else b.url))
        if out:
            rows.append(out)
    return rows


def vk_payload(peer, m, random_id=None) -> dict:
    """random_id makes VK drop a repeated send: unique per real send, a placeholder in the preview."""
    rows = buttons(m)[:6]
    body = {"peer_id": peer, "message": plain(m.get("text", ""))[:4000] or "…",
            "random_id": secrets.randbelow(2**31) if random_id is None else random_id}
    if m.get("photo") or m.get("document"):
        body["message"] += "\n\n(вложение доступно в Telegram и в кабинете)"
    if rows:
        body["keyboard"] = json.dumps({"inline": True, "buttons": [[
            {"action": {"type": "callback", "label": t[:40], "payload": json.dumps({"cmd": v})}} if k == "callback"
            else {"action": {"type": "open_link", "label": t[:40], "link": v}} for t, k, v in row[:5]] for row in rows]},
            ensure_ascii=False)
    return body


def max_payload(chat, m) -> dict:
    rows = buttons(m)
    body: dict = {"chat_id": chat, "text": (m.get("text") or "…")[:4000], "format": "html"}
    if rows:
        body["attachments"] = [{"type": "inline_keyboard", "payload": {"buttons": [[
            {"type": "callback", "text": t, "payload": v} if k == "callback" else {"type": "link", "text": t, "url": v}
            for t, k, v in row] for row in rows]}}]
    return body


def formats(messages) -> dict:
    """What each channel's API would receive for these answers — shown by the cabinet's emulator."""
    return {"vk": [vk_payload("<peer_id>", m, "<random_id>") for m in messages],
            "max": [max_payload("<chat_id>", m) for m in messages]}


# ---------------------------------------------------------------- inbound → the core's update shape


def from_vk(event) -> dict | None:
    o = event.get("object") or {}
    if event.get("type") == "message_new":
        msg = o.get("message") or {}
        payload = json.loads(msg.get("payload") or "{}") if msg.get("payload") else {}
        who = {"id": f"vk:{msg.get('from_id')}", "first_name": "Гость VK"}
        chat = {"id": f"vk:{msg.get('peer_id')}", "type": "private"}
        if payload.get("cmd"):
            return {"update_id": "vk-" + str(event.get("event_id")), "callback_query": {
                "id": None, "from": who, "data": payload["cmd"], "message": {"chat": chat, "from": who}}}
        return {"update_id": "vk-" + str(event.get("event_id")), "message": {"from": who, "chat": chat, "text": msg.get("text", "")}}
    if event.get("type") == "message_event":
        who = {"id": f"vk:{o.get('user_id')}", "first_name": "Гость VK"}
        chat = {"id": f"vk:{o.get('peer_id')}", "type": "private"}
        cmd = (o.get("payload") or {}).get("cmd")
        if cmd:
            return {"update_id": "vk-" + str(event.get("event_id")), "callback_query": {
                "id": f"vk:{o.get('event_id')}:{o.get('user_id')}:{o.get('peer_id')}", "from": who, "data": cmd,
                "message": {"chat": chat, "from": who}}}
    return None


def from_max(update) -> dict | None:
    kind = update.get("update_type")
    if kind == "message_created":
        m = update.get("message") or {}
        who = {"id": f"max:{(m.get('sender') or {}).get('user_id')}", "first_name": "Гость MAX"}
        chat = {"id": f"max:{(m.get('recipient') or {}).get('chat_id')}", "type": "private"}
        return {"update_id": "max-" + str(m.get("body", {}).get("mid") or update.get("timestamp")),
                "message": {"from": who, "chat": chat, "text": (m.get("body") or {}).get("text", "")}}
    if kind == "message_callback":
        cb = update.get("callback") or {}
        msg = update.get("message") or {}
        who = {"id": f"max:{(cb.get('user') or {}).get('user_id')}", "first_name": "Гость MAX"}
        chat = {"id": f"max:{(msg.get('recipient') or {}).get('chat_id')}", "type": "private"}
        return {"update_id": "max-" + str(cb.get("callback_id")), "callback_query": {
            "id": "max:" + str(cb.get("callback_id")), "from": who, "data": cb.get("payload"), "message": {"chat": chat, "from": who}}}
    return None


# ---------------------------------------------------------------- outbound


def deliver(chat: str, messages, callback_id=None):
    channel, _, target = chat.partition(":")
    if channel == "vk":
        token = os.environ["VK_TOKEN"]
        if callback_id:  # stop the spinner on the pressed button
            _, event_id, user_id, peer = callback_id.split(":", 3)
            httpx.post(VK_API + "messages.sendMessageEventAnswer", timeout=10, data={
                "access_token": token, "v": "5.199", "event_id": event_id, "user_id": user_id, "peer_id": peer})
        for m in messages:
            httpx.post(VK_API + "messages.send", timeout=10, data={**vk_payload(int(target), m), "access_token": token, "v": "5.199"})
    elif channel == "max":
        headers = {"Authorization": os.environ["MAX_TOKEN"]}
        if callback_id:
            httpx.post(MAX_API + "answers", params={"callback_id": callback_id.split(":", 1)[1]}, json={"notification": ""},
                       headers=headers, timeout=10)
        for m in messages:
            body = max_payload(int(target), m)
            httpx.post(MAX_API + "messages", params={"chat_id": body.pop("chat_id")}, json=body, headers=headers, timeout=10)
    return {"sent": len(messages)}


def process(data):
    """Worker side: the core answers, the channel's adapter delivers."""
    from .telegram import handle

    r = handle(data["update"])
    if not r:
        return {"ignored": True}
    chat, out, callback_id, _ = r
    return deliver(str(chat), out, callback_id)


def enqueue(update, channel):
    with db() as s:
        key = channel + ":" + str(update["update_id"])
        if s.get(System, key):
            return False
        s.add(System(key=key, data={"received": now().isoformat()}))
        s.add(Job(kind="channel", data={"channel": channel, "update": update}, result={}))
        return True


# ---------------------------------------------------------------- webhooks


@router.post("/api/v1/vk/callback")
async def vk_callback(request: Request):
    if not os.getenv("VK_TOKEN"):
        return PlainTextResponse("not configured", 404)
    event = await request.json()
    if event.get("type") == "confirmation":
        return PlainTextResponse(os.getenv("VK_CONFIRMATION", ""))
    if not secrets.compare_digest(str(event.get("secret", "")), os.getenv("VK_SECRET", "")):
        return PlainTextResponse("forbidden", 403)
    update = from_vk(event)
    if update:
        enqueue(update, "vk")
    return PlainTextResponse("ok")  # VK expects exactly «ok», or it retries


@router.post("/api/v1/max/webhook")
async def max_webhook(request: Request):
    if not os.getenv("MAX_TOKEN"):
        return PlainTextResponse("not configured", 404)
    if not secrets.compare_digest(request.headers.get("x-max-bot-api-secret", ""), os.getenv("MAX_SECRET", "")):
        return PlainTextResponse("forbidden", 403)
    update = from_max(await request.json())
    if update:
        enqueue(update, "max")
    return {"ok": True}


@router.get("/api/v1/channels")
def channels_view():
    return {"telegram": bool(os.getenv("TELEGRAM_BOT_TOKEN")), "vk": bool(os.getenv("VK_TOKEN")), "max": bool(os.getenv("MAX_TOKEN"))}
