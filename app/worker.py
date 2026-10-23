import time, os, asyncio, traceback, shutil
from datetime import timedelta
from sqlalchemy import select, delete, text
from .db import db, Job, System, Space, Booking, Item, AccessToken, FILES, now
from .domain import cansee, bill, today, audit, update
from .seed import refill_pool


def notify(job):
    from .telegram import send

    with db() as s:
        sp = s.get(Space, job.space)
        if not sp or not os.getenv("TELEGRAM_BOT_TOKEN") or not sp.data.get("tg_chat"):
            return {"channel": "in_app", "telegram": "not_linked"}
        if not sp.data.get("pd_consent") or not sp.data.get("tg_role_chosen"):
            return {"telegram": "onboarding_required"}
        if job.data.get("via") == "telegram":
            return {"telegram": "answered_in_chat"}
        if job.data.get("target"):
            item = s.scalar(
                select(Item).where(Item.space == sp.id, Item.id == job.data["target"])
            )
            if not item or not cansee(s, sp, item):
                return {"telegram": "out_of_scope"}
        chat = sp.data["tg_chat"]
        title = job.data["title"]
        route = "web" if sp.role in ("owner", "admin", "manager", "service", "finance", "screening") else None
        if job.data.get("target") and sp.role in ("driver", "client"):
            if item.kind == "contract":
                route = "rentals/" + item.id if sp.role == "client" else "driver"
            elif item.kind == "ticket" and sp.role == "driver":
                route = "driver/tickets/" + item.id
            elif item.kind == "source_record" and sp.role == "driver":
                route = "driver/fines/" + item.id
            elif item.kind == "demo_payment":
                route = "profile"
    asyncio.run(send(chat, title, route))
    return {"telegram": "sent"}


def morning_digest():
    """09:00 MSK: the owner's digest to every space linked to Telegram, once a day."""
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        return
    from .digest import build, due_spaces
    from .telegram import _deliver, kb

    with db() as s:
        targets = [(sp.data["tg_chat"], build(s, sp)) for sp in due_spaces(s)]
    for chat, text in targets:
        try:
            asyncio.run(_deliver(chat, [{"text": text, "kb": kb([("📊 Дашборд", "web")])}]))
        except Exception as e:
            print("digest failed", type(e).__name__, flush=True)


def maintenance():
    with db() as s:
        h = s.get(System, "worker")
        if not h:
            s.add(System(key="worker", data={"heartbeat": now().isoformat()}))
        else:
            h.data = {"heartbeat": now().isoformat()}
        s.query(Booking).filter(
            Booking.state == "hold", Booking.expires < now()
        ).update({"state": "expired"})
        s.execute(
            delete(AccessToken).where(AccessToken.created < now() - timedelta(hours=24))
        )
        expired = s.scalars(
            select(Space).where(Space.touched < now() - timedelta(hours=24))
        ).all()
        for sp in expired:
            folder = (FILES / sp.id).resolve()
            if folder.parent == FILES.resolve() and folder.exists():
                shutil.rmtree(folder)
            s.delete(sp)
    with db() as s:
        ids = s.scalars(
            select(Space.id).where(
                Space.touched >= now() - timedelta(hours=24),
                ~Space.data.has_key("pool"),  # заготовки пула не биллингуются
            )
        ).all()
    for sid in ids:
        with db() as s:
            sp = s.scalar(
                select(Space).where(Space.id == sid).with_for_update(skip_locked=True)
            )
            if not sp:
                continue
            if sp.data.get("last_billed") != str(today()) and str(today())[
                :7
            ] not in sp.data.get("closed_months", []):
                for c in s.scalars(
                    select(Item).where(
                        Item.space == sid,
                        Item.kind == "contract",
                        Item.data["status"].astext == "active",
                    )
                ):
                    bill(s, sp, c)
                sp.data = {**sp.data, "last_billed": str(today())}
            for ticket in s.scalars(
                select(Item).where(
                    Item.space == sid,
                    Item.kind == "ticket",
                    Item.data["status"].astext == "new",
                )
            ):
                if (
                    not ticket.data.get("escalated")
                    and not ticket.data.get("answered_at")
                    and __import__("datetime").datetime.fromisoformat(
                        ticket.data["due"]
                    )
                    < now()
                ):
                    update(ticket, escalated=True)
                    audit(
                        s,
                        sp,
                        "Просрочена реакция: " + ticket.data["title"],
                        ticket.id,
                        escalation=True,
                    )


def main():
    last = 0
    while True:
        try:
            if time.monotonic() - last > 20:
                maintenance()
                morning_digest()
                last = time.monotonic()
                try:
                    with db() as s:
                        refill_pool(s)
                except Exception:
                    traceback.print_exc()
            with db() as s:
                j = s.scalar(
                    select(Job)
                    .where(
                        ((Job.state == "pending") & (Job.due <= now()))
                        | ((Job.state == "running") & (Job.lease < now()))
                    )
                    .order_by(Job.due)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if j:
                    # Never blindly repeat an AI request with an ambiguous billable outcome.
                    if j.state == "running" and j.kind in ("ai", "call"):
                        j.state = "failed"
                        j.result = {
                            "error": "Обработка прервана. Расход зарезервирован; повторите запрос вручную."
                        }
                        continue
                    j.state = "running"
                    j.attempts += 1
                    j.lease = now() + timedelta(minutes=6)
            if not j:
                time.sleep(1)
                continue
            try:
                if j.kind == "ai":
                    from .ai import run

                    result = run(j)
                elif j.kind == "telegram":
                    from .telegram import process

                    result = process(j.data)
                elif j.kind == "telegram_sim":
                    from .telegram import simulate

                    result = simulate(j.data)
                elif j.kind in ("integration", "integration_trace"):
                    from .integrations import execute

                    result = execute(j)
                elif j.kind == "notify":
                    result = notify(j)
                elif j.kind == "inbox":
                    from .inbox import run_job

                    result = run_job(j)
                elif j.kind == "call":
                    from .calls import review

                    result = {"score": review(j.space, j.data["call"])["score"]}
                elif j.kind == "cleanup_files":
                    sid = j.data.get("space", "")
                    folder = (FILES / sid).resolve()
                    with db() as s:
                        exists = s.get(Space, sid)
                    if (
                        not exists
                        and len(sid) == 32
                        and folder.parent == FILES.resolve()
                        and folder.is_dir()
                    ):
                        shutil.rmtree(folder)
                    result = {"cleaned": not exists}
                else:
                    result = {"ignored": True}
                with db() as s:
                    current = s.get(Job, j.id)
                    if current:
                        current.state = "done"
                        current.result = result
            except Exception as e:
                print("job failed", j.kind, type(e).__name__, str(e)[:200] if j.kind == "inbox" else "", flush=True)
                with db() as s:
                    current = s.get(Job, j.id)
                    if current:
                        current.result = {
                            "error": (
                                str(e)[:500]
                                if not hasattr(e, "request")
                                else "Внешний сервис отклонил запрос. Проверьте соединение и лимиты."
                            )
                        }
                        current.state = (
                            "failed"
                            if j.kind in ("ai", "call") or current.attempts >= 3
                            else "pending"
                        )
                        current.due = now() + timedelta(seconds=10 * current.attempts)
        except Exception as e:
            print("worker error", type(e).__name__, flush=True)
            time.sleep(3)


if __name__ == "__main__":
    main()
