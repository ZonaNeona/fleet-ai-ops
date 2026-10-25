"""A Playwright robot that checks the fleet's fines on the training portal (app/gov.py) and reconciles them with what
n8n delivered to the ledger.

What it does, step by step — every step is timed and photographed:
    open the portal → paste the fleet's plates → read the captcha stub's test code → search
    → walk the pages (throttled; a 503 is retried with back-off; a 429 waits and retries)
    → reconcile: on the portal and in the ledger · only on the portal · amount differs · only in the ledger

The browser runs in a short subprocess (python -m app.robot <run id>), like the documents graph: Chromium never stays
in the worker's memory. Found fines can be loaded into the ledger as the same records n8n writes, so a driver sees
them in the Mini App.
"""

import os
import re
import sys
import time
from datetime import timedelta
from decimal import Decimal

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from .db import FILES, Item, Job, db, now
from .domain import audit, fail
from .seed import add

router = APIRouter()
VIEW = {"owner", "admin", "finance", "manager"}
BASE = os.getenv("ROBOT_BASE", "http://127.0.0.1:3008")
DIRECTIONS = ("taxi", "buyout")  # the drivers whose fines the fleet pays first and recovers


# ---------------------------------------------------------------- the browser part (subprocess)


def crawl(plates: list[str], shots_dir, step) -> list[dict]:
    from playwright.sync_api import sync_playwright

    rows: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width": 1100, "height": 820}, locale="ru-RU")

        def snap(title, status="success", **extra):
            n = len(step.steps) + 1
            path = shots_dir / f"{n:02d}.jpg"
            page.screenshot(path=str(path), type="jpeg", quality=55)
            step(title, status, shot=path.name, url=page.url.replace(BASE, ""), **extra)

        page.goto(BASE + "/gov", wait_until="domcontentloaded")
        snap("Открыт портал")
        page.fill("#plates", "\n".join(plates))
        snap(f"Вставлено госномеров: {len(plates)}")
        code = page.get_attribute("[data-test-code]", "data-test-code")  # the stub's test hook, see app/gov.py
        page.fill("#captcha", code or "")
        snap("Капча-заглушка: код из тестового атрибута")
        page.click("button[type=submit]")
        page.wait_for_load_state("domcontentloaded")
        while True:
            for attempt in range(4):
                title = page.title()
                if "503" in title or "429" in title:
                    wait = 1.0 * (attempt + 1)
                    snap(
                        f"Портал ответил {'503 — перегружен' if '503' in title else '429 — слишком часто'}, "
                        f"повтор через {wait:.0f} с",
                        "retry",
                    )
                    time.sleep(wait)
                    page.reload(wait_until="domcontentloaded")
                    continue
                break
            else:
                snap("Портал не ответил после повторов — остановка", "error")
                break
            found = page.eval_on_selector_all(
                "#fines tbody tr",
                """trs => trs.filter(tr => tr.cells.length === 6).map(tr => ({
                plate: tr.cells[0].innerText.trim(), resolution: tr.cells[1].innerText.trim(), date: tr.cells[2].innerText.trim(),
                article: tr.cells[3].innerText.split('\\n')[0].trim(), amount: Number(tr.cells[4].dataset.amount),
                discount_until: tr.cells[5].innerText.trim() }))""",
            )
            rows += found
            label = page.inner_text(".pager span") if page.query_selector(".pager span") else ""
            snap(f"{label or 'Страница'}: постановлений на странице — {len(found)}")
            nxt = page.query_selector("a[rel=next]")
            if not nxt:
                break
            time.sleep(0.4)  # the portal answers 429 to anything faster
            nxt.click()
            page.wait_for_load_state("domcontentloaded")
        browser.close()
    return rows


class Steps:
    def __init__(self):
        self.steps: list[dict] = []
        self.started = time.monotonic()

    def __call__(self, title, status="success", **extra):
        self.steps.append(
            {"title": title, "status": status, "ms": round((time.monotonic() - self.started) * 1000), **extra}
        )


def main(run_id: str):
    with db() as s:
        run = s.get(Item, run_id)
        plates = [
            v.data["plate"]
            for v in s.scalars(
                select(Item)
                .where(Item.space == run.space, Item.kind == "vehicle", Item.data["direction"].astext.in_(DIRECTIONS))
                .order_by(Item.code)
            )
        ]
        space = run.space
    shots = FILES / space / "robot" / run_id
    shots.mkdir(parents=True, exist_ok=True)
    steps = Steps()
    error = None
    rows: list[dict] = []
    try:
        rows = crawl(plates, shots, steps)
    except Exception as e:  # the run is reported, not lost
        error = f"{type(e).__name__}: {str(e)[:200]}"
        steps("Робот остановился с ошибкой", "error", error=error)
    with db() as s:
        run = s.get(Item, run_id)
        rec = reconcile(s, run.space, rows)
        run.data = {
            **run.data,
            "status": "failed" if error else "done",
            "steps": steps.steps,
            "rows": rows,
            "reconciliation": rec,
            "plates": len(plates),
            "finished": now().isoformat(),
            "error": error,
            "seconds": round(time.monotonic() - steps.started, 1),
        }
        run.version += 1


# ---------------------------------------------------------------- reconciliation and import


def ledger_fines(s, space):
    out = {}
    for x in s.scalars(
        select(Item).where(Item.space == space, Item.kind == "source_record", Item.data["source"].astext == "fines")
    ):
        v = x.data.get("values") or {}
        if v.get("external_id"):
            out[v["external_id"]] = {
                "amount": Decimal(str(v.get("fine") or 0)),
                "code": v.get("vehicle_code"),
                "via": v.get("via", "n8n"),
            }
    return out


def reconcile(s, space, rows):
    known = ledger_fines(s, space)
    out = []
    for r in rows:
        mine = known.pop(r["resolution"], None)
        amount = Decimal(str(r["amount"]))
        if not mine:
            out.append({**r, "state": "portal-only", "note": "есть на портале, в учёте нет"})
        elif mine["amount"] != amount:
            out.append(
                {
                    **r,
                    "state": "amount",
                    "ledger": str(mine["amount"]),
                    "note": f"в учёте {mine['amount']:.0f} ₽, на портале {amount:.0f} ₽",
                }
            )
        else:
            out.append({**r, "state": "ok", "note": "сходится"})
    for resolution, mine in known.items():
        out.append(
            {
                "resolution": resolution,
                "plate": mine["code"],
                "amount": float(mine["amount"]),
                "state": "ledger-only",
                "note": "в учёте есть, на портале не найден — возможно, уже оплачен",
            }
        )
    return out


def load(s, sp, run):
    """Portal-only fines → the ledger, as the same source records n8n writes (the Mini App shows them to the driver)."""
    vehicles = {v.data["plate"]: v for v in s.scalars(select(Item).where(Item.space == sp.id, Item.kind == "vehicle"))}
    added = 0
    for r in run.data.get("reconciliation", []):
        if r["state"] != "portal-only" or r["plate"] not in vehicles:
            continue
        v = vehicles[r["plate"]]
        code = "fines:robot:" + r["resolution"]
        if s.scalar(select(Item.id).where(Item.space == sp.id, Item.kind == "source_record", Item.code == code)):
            continue
        add(
            s,
            sp.id,
            "source_record",
            code,
            {
                "source": "fines",
                "vehicle": v.id,
                "at": now().isoformat(),
                "run": run.id,
                "values": {
                    "vehicle_code": v.code,
                    "fine": f"{Decimal(str(r['amount'])):.2f}",
                    "external_id": r["resolution"],
                    "discount_percent": 50,
                    "discount_until": r.get("discount_until"),
                    "via": "robot",
                    "discount_rule": "Учебное условие портала: скидка 50% до указанной даты",
                },
            },
        )
        added += 1
    for r in run.data.get("reconciliation", []):
        if r["state"] == "portal-only" and r["plate"] in vehicles:
            r.update(state="loaded", note="загружено в учёт роботом")
    run.data = {**run.data, "reconciliation": run.data.get("reconciliation", []), "loaded": added}
    run.version += 1
    audit(s, sp, f"Робот загрузил в учёт постановлений: {added}", run.id)
    return added


# ---------------------------------------------------------------- the cabinet


def available() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


def viewer(s, request):
    from .api import auth

    sp = auth(s, request)
    if sp.role not in VIEW:
        fail("Робот доступен собственнику, финансисту и менеджеру", 403)
    return sp


def view(run):
    return {"id": run.id, "created": run.created.isoformat(), **run.data}


@router.get("/api/v1/robot")
def robot_view(request: Request):
    with db() as s:
        sp = viewer(s, request)
        run = s.scalar(select(Item).where(Item.space == sp.id, Item.kind == "robot_run").order_by(Item.created.desc()))
        # Without fines from n8n the reconciliation has nothing to compare with: the console offers to fetch them first.
        return {"available": available(), "run": view(run) if run else None, "ledger": len(ledger_fines(s, sp.id))}


@router.post("/api/v1/robot/run")
def robot_run(request: Request):
    if not available():
        fail("Playwright не установлен на этом сервере", 409)
    with db() as s:
        sp = viewer(s, request)
        busy = s.scalar(
            select(func.count()).select_from(Job).where(Job.kind == "robot", Job.state.in_(["pending", "running"]))
        )
        if busy:
            fail("Робот уже работает — одна сессия браузера на сервер", 429)
        recent = s.scalar(
            select(func.count())
            .select_from(Item)
            .where(Item.space == sp.id, Item.kind == "robot_run", Item.created > now() - timedelta(hours=1))
        )
        if recent >= 5:
            fail("Не больше пяти запусков робота в час", 429)
        run = add(s, sp.id, "robot_run", "ROBOT-" + now().strftime("%H%M%S"), {"status": "queued", "steps": []})
        s.flush()
        s.add(Job(space=sp.id, kind="robot", data={"run": run.id}))
        return view(run)


@router.post("/api/v1/robot/{run_id}/load")
def robot_load(run_id: str, request: Request):
    with db() as s:
        sp = viewer(s, request)
        run = s.get(Item, run_id)
        if not run or run.space != sp.id or run.kind != "robot_run" or run.data.get("status") != "done":
            fail("Запуск не найден", 404)
        return {"loaded": load(s, sp, run), "run": view(run)}


@router.get("/api/v1/robot/{run_id}/shot/{name}")
def robot_shot(run_id: str, name: str, request: Request):
    if not re.fullmatch(r"\d{2}\.jpg", name):
        fail("Нет такого снимка", 404)
    with db() as s:
        sp = viewer(s, request)
        run = s.get(Item, run_id)
        if not run or run.space != sp.id or run.kind != "robot_run":
            fail("Запуск не найден", 404)
    path = FILES / sp.id / "robot" / run_id / name
    if not path.exists():
        fail("Нет такого снимка", 404)
    return FileResponse(path, media_type="image/jpeg")


def run_job(job):
    """Worker side: the browser lives in a subprocess for the length of one run."""
    import subprocess
    from pathlib import Path

    with db() as s:
        run = s.get(Item, job.data["run"])
        run.data = {**run.data, "status": "running", "started": now().isoformat()}
    r = subprocess.run(
        [sys.executable, "-m", "app.robot", job.data["run"]],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=Path(__file__).parent.parent,
        env={**os.environ, "MALLOC_ARENA_MAX": "2"},
    )
    if r.returncode:  # reported on the run, not retried: a second browser run would only repeat the failure
        error = (r.stderr.strip().splitlines() or ["робот завершился с ошибкой"])[-1][:300]
        with db() as s:
            run = s.get(Item, job.data["run"])
            run.data = {**run.data, "status": "failed", "error": error}
        return {"run": job.data["run"], "error": error}
    return {"run": job.data["run"]}


if __name__ == "__main__":
    main(sys.argv[1])
