"""A training «госуслуга»: a fines portal for the Playwright robot to work against.

It behaves like the portals such robots meet in real life, and nothing more:
    /gov                   a form: a list of plates, a captcha
    POST /gov/search       the search → /gov/results/<id>?page=N, ten rows a page
    page 2 answers 503 the first time it is asked (a portal under load) — the robot must retry
    two requests to one search within 0.3 s get 429 — the robot must throttle

The captcha is a stub, and says so: on a training stand its code is exposed to automated tests (data-test-code),
the way test environments switch captchas off. A real portal needs an operator or a contractual API — a robot does
not solve captchas.

Fines are derived from the plate, deterministically: the four that n8n delivers to the ledger (one with another
amount) and a few that only the portal knows — so the robot's reconciliation has something to find.
"""

import hashlib
from html import escape
import math
import re
import secrets
import time
from datetime import date, timedelta

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from .db import System, db
from .domain import today

router = APIRouter()
PAGE = 10
N8N = {"TP-0002": 500, "TP-0004": 500, "TP-0011": 1000, "TP-0026": 500}  # TP-0011: n8n says 500, the portal 1000
ARTICLES = [("12.9 ч.2", "Превышение скорости на 20–40 км/ч", 500), ("12.12 ч.1", "Проезд на запрещающий сигнал", 1000),
            ("12.16 ч.3", "Движение во встречном направлении по дороге с односторонним движением", 5000),
            ("12.19 ч.5", "Стоянка в запрещённом месте (Москва)", 3000)]


def code_of(plate: str) -> str | None:
    m = re.search(r"(\d{4})", plate)
    return "TP-" + m.group(1) if m else None


def fines_for(plate: str):
    plate = re.sub(r"\s+", " ", plate.strip().upper())
    code = code_of(plate)
    if not code:
        return []
    h = int(hashlib.sha256(plate.encode()).hexdigest(), 16)
    rows = []
    if code in N8N:
        rows.append({"resolution": "DEMO-FINE-" + code, "plate": plate, "article": ARTICLES[0][0], "what": ARTICLES[0][1],
                     "date": str(today() - timedelta(days=4)), "amount": N8N[code]})
    if h % 7 == 0:  # only the portal knows about it yet
        article, what, amount = ARTICLES[h % len(ARTICLES)]
        rows.append({"resolution": "18810177" + str(h)[-12:], "plate": plate, "article": article, "what": what,
                     "date": str(today() - timedelta(days=1 + h % 9)), "amount": amount})
    for r in rows:
        r["discount_until"] = str(date.fromisoformat(str(r["date"])) + timedelta(days=20))
    return rows


def screen(body: str, title: str, status=200):
    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>{title} · учебный портал</title><style>
body{{margin:0;font:15px/1.5 Arial,sans-serif;background:#eef1f5;color:#0b1f33}}
header{{background:#0d4cd3;color:#fff;padding:14px 20px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}}
header b{{font-size:18px}} header span{{background:#ffd600;color:#0b1f33;font-size:12px;font-weight:700;padding:2px 8px;border-radius:4px}}
main{{max-width:880px;margin:20px auto;padding:0 16px}} .box{{background:#fff;border-radius:8px;padding:20px;margin-bottom:16px}}
label{{display:block;font-weight:700;margin:12px 0 6px}} textarea,input{{font:inherit;width:100%;box-sizing:border-box;padding:9px;border:1px solid #b7c0cc;border-radius:6px}}
button{{background:#0d4cd3;color:#fff;border:0;border-radius:6px;padding:11px 20px;font:700 15px Arial;cursor:pointer;margin-top:14px}}
table{{width:100%;border-collapse:collapse;font-size:14px}} th,td{{text-align:left;padding:8px;border-bottom:1px solid #e1e6ed;vertical-align:top}}
.pager{{display:flex;gap:12px;margin-top:14px;align-items:center}} .note{{font-size:13px;color:#66727f}} .err{{color:#b3261e;font-weight:700}}
.captcha{{display:flex;gap:12px;align-items:center}} .captcha input{{max-width:160px}}
</style></head><body><header><b>Госуслуги · Штрафы ГИБДД</b><span>УЧЕБНЫЙ ПОРТАЛ СТЕНДА</span></header><main>{body}</main></body></html>"""
    return HTMLResponse(html, status_code=status, headers={"X-Robots-Tag": "noindex"})


def captcha_svg(code: str, seed: int) -> str:
    glyphs = "".join(
        f'<text x="{14 + i * 26}" y="{34 + (seed >> i) % 7}" transform="rotate({((seed >> (i * 2)) % 21) - 10} {20 + i * 26} 28)">{d}</text>'
        for i, d in enumerate(code))
    lines = "".join(f'<line x1="0" y1="{(seed >> k) % 48}" x2="150" y2="{(seed >> (k + 3)) % 48}" stroke="#8aa" />' for k in range(4))
    return (f'<svg width="150" height="48" viewBox="0 0 150 48" role="img" aria-label="Код с картинки">'
            f'<rect width="150" height="48" fill="#f3f5f8"/>{lines}'
            f'<g font-family="Courier New" font-size="28" font-weight="700" fill="#33475b">{glyphs}</g></svg>')


@router.get("/gov", response_class=HTMLResponse)
def form(error: str = ""):
    cid, code = secrets.token_hex(8), f"{secrets.randbelow(90000) + 10000}"
    with db() as s:
        s.add(System(key="govcap:" + cid, data={"code": code, "at": time.time()}))
    svg = captcha_svg(code, int(cid, 16))
    err = f'<p class="err">{ {"captcha": "Неверный код с картинки", "plates": "Укажите от 1 до 200 госномеров"}.get(error, "") }</p>' if error else ""
    return screen(f"""<div class="box"><h1>Проверка штрафов по списку ТС</h1>
<p class="note">Для юридических лиц и автопарков: до 200 госномеров за раз. Данные учебные.</p>{err}
<form method="post" action="/gov/search">
<label for="plates">Госномера, по одному в строке</label><textarea id="plates" name="plates" rows="6" placeholder="ДЕМО 0002"></textarea>
<label for="captcha">Код с картинки</label>
<div class="captcha"><span data-test-code="{code}">{svg}</span><input id="captcha" name="captcha" autocomplete="off" inputmode="numeric"></div>
<input type="hidden" name="captcha_id" value="{cid}">
<button type="submit">Найти штрафы</button></form></div>
<p class="note">Капча-заглушка учебного стенда: её код доступен автотестам через атрибут <code>data-test-code</code>, как на тестовых
контурах. На настоящем портале капчу проходит человек или используется договорной API — робот капчи не решает.</p>""",
                "Проверка штрафов")


@router.post("/gov/search")
def search(plates: str = Form(""), captcha: str = Form(""), captcha_id: str = Form("")):
    with db() as s:
        row = s.get(System, "govcap:" + captcha_id[:20])
        ok = row is not None and row.data["code"] == captcha.strip() and row.data["at"] > time.time() - 600
        if row is not None:
            s.delete(row)  # a code works once
        if not ok:
            return RedirectResponse("/gov?error=captcha", 303)
        items = [p.strip() for p in plates.splitlines() if p.strip()][:200]
        if not items:
            return RedirectResponse("/gov?error=plates", 303)
        sid = secrets.token_hex(8)
        s.add(System(key="govsearch:" + sid, data={"plates": items, "at": time.time(), "seen": [], "last": 0}))
    return RedirectResponse(f"/gov/results/{sid}?page=1", 303)


@router.get("/gov/results/{sid}", response_class=HTMLResponse)
def results(sid: str, page: int = 1):
    n = page
    with db() as s:
        row = s.get(System, "govsearch:" + sid[:20])
        if not row or row.data["at"] < time.time() - 1800:
            return screen('<div class="box"><h1>Поиск устарел</h1><a href="/gov">Новый поиск</a></div>', "Устарел", 404)
        data = dict(row.data)
        if time.time() - data.get("last", 0) < 0.3:
            return screen('<div class="box"><h1>Слишком частые запросы</h1><p>Повторите через секунду.</p></div>', "429", 429)
        data["last"] = time.time()
        if n == 2 and 2 not in data["seen"]:  # the portal is under load the first time page 2 is asked
            data["seen"] = data["seen"] + [2]
            row.data = data
            return screen('<div class="box"><h1>Сервис временно недоступен</h1><p>Повторите запрос позже.</p></div>', "503", 503)
        row.data = data
    found = [f for p in data["plates"] for f in fines_for(p)]
    pages = max(1, math.ceil(len(data["plates"]) / PAGE))
    n = max(1, min(n, pages))
    chunk = data["plates"][(n - 1) * PAGE:n * PAGE]
    rows = [f for p in chunk for f in fines_for(p)]
    body = "".join(  # the plate is what the visitor typed: escaped like everything else on the page
        f"<tr><td>{escape(str(r['plate']))}</td><td>{r['resolution']}</td><td>{r['date']}</td><td>{r['article']}<br>"
        f"<span class='note'>{r['what']}</span></td><td data-amount='{r['amount']}'>{r['amount']:,} ₽</td>"
        f"<td>{r['discount_until']}</td></tr>".replace(f"{r['amount']:,}", f"{r['amount']:,}".replace(",", " "))
        for r in rows)
    nav = (f'<a rel="prev" href="/gov/results/{sid}?page={n - 1}">← Назад</a>' if n > 1 else "") + \
          f"<span>Страница {n} из {pages}</span>" + \
          (f'<a rel="next" href="/gov/results/{sid}?page={n + 1}">Следующая →</a>' if n < pages else "")
    return screen(f"""<div class="box"><h1>Найдено постановлений: {len(found)}</h1>
<p class="note">Проверено ТС: {len(data['plates'])}. На этой странице — ТС {(n - 1) * PAGE + 1}–{(n - 1) * PAGE + len(chunk)}.</p>
<table id="fines"><thead><tr><th>ТС</th><th>Постановление</th><th>Дата</th><th>Статья</th><th>Сумма</th><th>Скидка до</th></tr></thead>
<tbody>{body or '<tr><td colspan="6">На этой странице штрафов нет</td></tr>'}</tbody></table>
<div class="pager">{nav}</div></div>""", f"Результаты · стр. {n}")


def sweep(s):
    """Old captcha codes and searches: they are for minutes, not for keeps."""
    from sqlalchemy import delete

    s.execute(delete(System).where(System.key.like("govcap:%"), System.data["at"].as_float() < time.time() - 3600))
    s.execute(delete(System).where(System.key.like("govsearch:%"), System.data["at"].as_float() < time.time() - 3600))
