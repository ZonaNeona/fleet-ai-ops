"""Bot scenarios without Telegram: updates go through process(), outgoing messages are printed instead of sent.

Run on the host: .venv/bin/python -m scripts.bot_smoke
The test space (tg_user=9000001) is removed at the end.
"""

import itertools
import json
import os
import re
import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, func, select

from app import domain, telegram
from app.db import Event, Item, Job, Space, db

TG = 9000001
checks = []
seq = itertools.count(900000000)
last_kb: list[list[str]] = []


async def fake_deliver(chat, messages, callback_id=None):
    global last_kb
    last_kb = []  # buttons of all messages of one answer
    for m in messages:
        text = re.sub(r"<[^>]+>", "", m.get("text", ""))
        tag = "📷 " if m.get("photo") else "📄 " if m.get("document") else ""
        print("   ←", tag + text.replace("\n", " | ")[:230])
        if m.get("kb"):
            buttons = [
                b.callback_data or ("app" if b.web_app else b.url) for row in m["kb"].inline_keyboard for b in row
            ]
            last_kb += buttons
            print("     [" + ", ".join(buttons) + "]")


telegram._deliver = fake_deliver


# Smoke never creates outgoing notification jobs for the synthetic Telegram user.
def local_audit(s, sp, title, target=None, **data):
    s.add(Event(space=sp.id, title=title, target=target, role=sp.role, data=data))


domain.audit = local_audit
user = {"id": TG, "first_name": "Тест"}
chat = {"id": TG, "type": "private"}


def msg(text):
    print(f"\n→ «{text}»")
    telegram.process(
        {
            "update_id": next(seq),
            "message": {"message_id": 1, "from": user, "chat": chat, "text": text},
        }
    )


def tap(data):
    print(f"\n→ [{data}]")
    telegram.process(
        {
            "update_id": next(seq),
            "callback_query": {
                "id": "cb",
                "from": user,
                "data": data,
                "message": {"message_id": 2, "chat": chat},
            },
        }
    )


def space():
    with db() as s:
        sp = s.scalar(select(Space).where(Space.data["tg_user"].astext == str(TG)))
        return sp.role, dict(sp.data)


def first(prefix):
    return next((x for x in last_kb if x and x.startswith(prefix)), None)


def inspect(tool=None):
    with db() as s:
        sp = s.scalar(select(Space).where(Space.data["tg_user"].astext == str(TG)))
        count = s.scalar(select(func.count()).select_from(Item).where(Item.space == sp.id, Item.kind == "ticket"))
        if tool:
            job = s.scalar(select(Job).where(Job.space == sp.id, Job.kind == "ai").order_by(Job.due.desc()))
            assert job and job.state == "done", "Agent job did not finish"
            assert any(t.get("title") == tool and t.get("status") == "success" for t in job.result["trace"]), tool
            if tool == "search_knowledge":
                assert job.result["sources"], "No knowledge citations"
            checks.append({"tool": tool, "passed": True, "model": job.result.get("model")})
        return count


try:
    msg("/start")
    assert first("role:driver"), "No role choice on /start"
    tap("role:driver")
    assert space()[0] == "driver", "Role was not set"
    checks.append({"start": "role choice without registration", "passed": True})
    tap("d:balance")
    tap("d:car")
    tap("d:holiday")
    msg("что ты умеешь?")
    msg("Сколько я должен?")
    inspect("get_balance")
    msg("Какие документы нужны, чтобы взять машину в аренду?")
    inspect("search_knowledge")
    before = inspect()
    msg("Стучит подвеска справа, нужна диагностика")
    if not first("agentconfirm:"):
        assert inspect() == before
        # This driver has two visible cars; correctly ask which one, then remember the problem.
        msg("TP-0002")
    inspect("create_ticket")
    assert inspect() == before, "Draft created a ticket without confirmation"
    draft = first("agentconfirm:")
    assert draft, "No confirmation button"
    tap(draft)
    assert inspect() == before + 1
    tap(draft)
    assert inspect() == before + 1, "Repeated confirmation duplicated the ticket"
    checks.append({"confirmation": "explicit and idempotent", "passed": True})
    tap("role:client")
    tap("c:catalog")
    book = first("c:dates:")
    assert book, "No calendar entry in rental catalog"
    tap(book)
    tap("c:pick:" + str(domain.today() + timedelta(days=1)))
    tap("c:pick:" + str(domain.today() + timedelta(days=8)))
    assert first("c:reserve"), "No booking confirmation after dates"
    tap("c:reserve")
    checks.append({"calendar": "inline dates and shared quote", "passed": True})
    tap("c:mine")
    tap("staff")
    tap("role:manager")
    tap("m:drafts")
    confirm = first("m:confirm:")
    if confirm:
        tap(confirm)
    tap("m:summary")
    tap("role:service")
    tap("s:tickets")
    est = first("s:est:")
    if est:
        tap(est)
    tap("role:finance")
    tap("f:estimates")
    approve = first("f:approve:")
    if approve:
        tap(approve)
    tap("f:holidays")
    hday = first("f:hday:")
    if hday:
        tap(hday)
    tap("f:economy")
    # the driver's traffic fines come through the n8n pipeline
    tap("role:driver")
    tap("d:fines")
    for _ in range(20):
        time.sleep(1.5)
        tap("d:fines")
        if first("d:ticket"):
            break
    assert first("d:ticket"), "Fine from GIBDD integration not shown"
    checks.append({"integration": "driver sees GIBDD fine via n8n", "passed": True})
finally:
    with db() as s:
        ids = s.scalars(select(Space.id).where(Space.data["tg_user"].astext == str(TG))).all()
        if ids:
            s.execute(delete(Space).where(Space.id.in_(ids)))
    print("\nтестовое пространство удалено:", len(ids))
    report_path = Path(os.getenv("BOT_REPORT_PATH", "reports/miniapp/bot-under.json"))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "checks": checks,
                "outgoing_messages": "intercepted; no Telegram delivery",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
