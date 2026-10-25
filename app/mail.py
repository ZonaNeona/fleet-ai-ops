"""Mail as a channel for incoming documents: an e-mail's attachments go through the same documents graph.

    POST /api/v1/inbox/eml        an .eml file uploaded in the cabinet (any mail client saves one)
    POST /api/v1/inbox/eml/sample a sample: a service station sends an invoice as a PDF with a text layer
    IMAP (IMAP_HOST, IMAP_USER, IMAP_PASSWORD)  the worker reads unseen mail every few minutes; plus-addressing
                                  (docs+<tag>@…) tells which demo space a letter belongs to

PDF and photos become documents; with no attachment the body itself is the document (a bill typed into a letter).
Sender, subject and date stay on the document, so the decision screen shows where it came from.
"""

import email
import imaplib
import os
import re
import secrets
import time
from email.message import EmailMessage
from email.policy import default
from email.utils import parseaddr, parsedate_to_datetime

from fastapi import APIRouter, File, Request, UploadFile
from sqlalchemy import select

from .db import FILES, Space, System, db, now, uid
from .domain import audit, fail, serialize
from .seed import add

router = APIRouter()
TYPES = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}
MAX_PARTS = 5
MAX_PART = 8 * 1024 * 1024
POLL_SECONDS = 300


def parse(raw: bytes):
    msg = email.message_from_bytes(raw, policy=default)
    sender = parseaddr(str(msg.get("from", "")))
    try:
        sent = parsedate_to_datetime(str(msg["date"])).isoformat() if msg["date"] else None
    except (TypeError, ValueError):
        sent = None
    parts = []
    for part in msg.iter_attachments():
        ext = TYPES.get(part.get_content_type()) or os.path.splitext(part.get_filename() or "")[1].lower()
        if ext not in (".pdf", ".jpg", ".jpeg", ".png"):
            continue
        data = part.get_payload(decode=True) or b""
        if 0 < len(data) <= MAX_PART:
            parts.append((part.get_filename() or "вложение" + ext, ext, data))
    body = msg.get_body(preferencelist=("plain",))
    text = body.get_content().strip() if body else ""
    return {
        "from": sender[1] or sender[0],
        "name": sender[0],
        "subject": str(msg.get("subject", ""))[:200],
        "date": sent,
        "to": [a for _, a in email.utils.getaddresses(msg.get_all("to", []) + msg.get_all("cc", []))],
        "parts": parts[:MAX_PARTS],
        "text": text[:18000],
    }


def ingest(s, sp, raw: bytes, source="mail"):
    """One letter → documents in the space's inbox, queued for the graph. Returns the documents."""
    from sqlalchemy import func

    from .db import Item
    from .inbox import create, enqueue

    pending = s.scalar(
        select(func.count())
        .select_from(Item)
        .where(
            Item.space == sp.id,
            Item.kind == "inbox",
            Item.data["status"].astext.in_(["new", "reading", "checking"]),
            Item.data["seed"].astext.is_distinct_from("true"),
        )
    )
    if pending >= 3:
        fail("Дождитесь обработки предыдущих документов", 429)
    letter = parse(raw)
    origin = {"from": letter["from"], "subject": letter["subject"], "date": letter["date"]}
    docs = []
    for name, ext, data in letter["parts"]:
        f = add(
            s,
            sp.id,
            "file",
            "F-" + uid()[:8],
            {"name": name[:120], "ext": ".jpg" if ext == ".jpeg" else ext, "size": len(data), "creator_role": "mail"},
        )
        (FILES / sp.id).mkdir(parents=True, exist_ok=True)
        (FILES / sp.id / (f.id + f.data["ext"])).write_bytes(data)
        docs.append(create(s, sp.id, source, file=f.id, name=name))
    if not docs and len(letter["text"]) > 40:
        docs.append(create(s, sp.id, source, text=letter["text"], name=letter["subject"] or "Письмо"))
    if not docs:
        fail("В письме нет PDF, фото или текста документа", 400)
    for d in docs:
        d.data = {**d.data, "mail": origin}
    s.flush()
    enqueue(s, sp.id, [d.id for d in docs])
    audit(s, sp, f"Письмо от {letter['from'] or 'неизвестного отправителя'}: документов — {len(docs)}", docs[0].id)
    return docs


def sample_letter(s, sp) -> bytes:
    """A service station sends an invoice: a real PDF with a text layer, so the graph reads it without a model."""
    from weasyprint import HTML

    from .inbox import sample

    text, _, _ = sample(s, sp, "invoice")
    pdf = HTML(
        string="<pre style='font:13px DejaVu Sans,sans-serif'>" + text.replace("<", "&lt;") + "</pre>"
    ).write_pdf()
    msg = EmailMessage()
    msg["From"] = "СТО «Мотор-Сервис» <sto@example.org>"
    msg["To"] = "docs@fleet.example"
    msg["Subject"] = "Счёт за ремонт по заявке"
    msg["Date"] = email.utils.format_datetime(now())
    msg.set_content(
        "Добрый день!\n\nВо вложении счёт за выполненные работы. Акт подпишем при выдаче машины.\n\nУчебное письмо стенда."
    )
    msg.add_attachment(pdf, maintype="application", subtype="pdf", filename="Счёт СТО.pdf")
    return bytes(msg)


# ---------------------------------------------------------------- the cabinet


def viewer(s, request):
    from .inbox import viewer as inbox_viewer

    return inbox_viewer(s, request)


@router.post("/api/v1/inbox/eml")
async def upload_eml(request: Request, file: UploadFile = File(...)):
    raw = await file.read(10 * 1024 * 1024 + 1)
    if len(raw) > 10 * 1024 * 1024:
        fail("Письмо больше 10 МБ")
    import anyio

    def run():
        with db() as s:
            sp = viewer(s, request)
            return [serialize(d) for d in ingest(s, sp, raw)]

    return {"docs": await anyio.to_thread.run_sync(run)}


@router.post("/api/v1/inbox/eml/sample")
def sample_eml(request: Request):
    with db() as s:
        sp = viewer(s, request)
        return {"docs": [serialize(d) for d in ingest(s, sp, sample_letter(s, sp))]}


@router.get("/api/v1/inbox/mailbox")
def mailbox(request: Request):
    """Where to send letters: with a mailbox configured, a plus-address that leads to this visitor's space."""
    with db() as s:
        sp = viewer(s, request)
        user = os.getenv("IMAP_USER", "")
        if not (os.getenv("IMAP_HOST") and user and "@" in user):
            return {"configured": False}
        tag = sp.data.get("mail_tag")
        if not tag:
            tag = secrets.token_hex(4)
            sp.data = {**sp.data, "mail_tag": tag}
        local, domain = user.split("@", 1)
        return {"configured": True, "address": f"{local}+{tag}@{domain}", "every_minutes": POLL_SECONDS // 60}


# ---------------------------------------------------------------- IMAP, from the worker


def poll():
    """Unseen letters → the space named by the plus-address. Every letter read is marked seen, including one for no
    known space, so the next poll never reads it twice."""
    host, user, password = os.getenv("IMAP_HOST"), os.getenv("IMAP_USER"), os.getenv("IMAP_PASSWORD")
    if not (host and user and password):
        return {"skipped": "IMAP не настроен"}
    with db() as s:
        mark = s.get(System, "mail_poll")
        if mark and mark.data.get("at", 0) > time.time() - POLL_SECONDS:
            return {"skipped": "рано"}
        if mark:
            mark.data = {"at": time.time()}
        else:
            s.add(System(key="mail_poll", data={"at": time.time()}))
    done = 0
    with imaplib.IMAP4_SSL(host, int(os.getenv("IMAP_PORT", "993")), timeout=30) as box:
        box.login(user, password)
        box.select("INBOX")
        _, found = box.search(None, "UNSEEN")
        for num in found[0].split()[:20]:
            _, data = box.fetch(num, "(RFC822)")
            raw = data[0][1] if data and isinstance(data[0], tuple) else b""
            box.store(num, "+FLAGS", "\\Seen")
            tags = re.findall(r"\+([0-9a-f]{8})@", " ".join(parse(raw)["to"]))
            if not tags:
                continue
            with db() as s:
                sp = s.scalar(select(Space).where(Space.data["mail_tag"].astext == tags[0]))
                if sp:
                    try:
                        ingest(s, sp, raw)
                        done += 1
                    except Exception:
                        pass
    return {"letters": done}
