"""The owner's tables: the morning digest, «сделать сейчас» and the documents registry as a spreadsheet.

    GET  /api/v1/export.xlsx      always works: an XLSX built here (openpyxl)
    POST /api/v1/export/sheets    mirrors the same three sheets into Google Sheets with a service account
                                  (GOOGLE_SA_JSON — path to its key file, GOOGLE_SHEET_ID — a table shared with it)

The service account's JWT is signed locally (google-auth) and exchanged for a token over plain HTTPS; the Sheets
API calls are three: add missing tabs, clear, write. Nothing is read back from the table — the stand stays the source.
"""

import io
import json
import os
import time
from datetime import datetime
from decimal import Decimal

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response
from sqlalchemy import select

from .db import Item, db, now
from .domain import fail

router = APIRouter()
VIEW = {"owner", "admin", "finance"}
SCOPE = "https://www.googleapis.com/auth/spreadsheets"
STATUS = {"posted": "проведён", "review": "ждёт решения", "mismatch": "расхождение", "rejected": "отклонён",
          "new": "в очереди", "reading": "читается", "checking": "сверяется", "failed": "ошибка"}


def number(v):
    """A recognised amount may arrive as «1 500,00 ₽»: a number for the table, or the text as it was."""
    if v in (None, ""):
        return ""
    try:
        return float(Decimal(str(v).replace(" ", "").replace(" ", "").replace("₽", "").replace(",", ".")))
    except ArithmeticError:
        return str(v)


def tables(s, sp) -> dict[str, list[list]]:
    from types import SimpleNamespace

    from .digest import build
    from .reports import report
    from .signals import compute

    owner = SimpleNamespace(id=sp.id, role="owner", data=sp.data)
    r = report(s, owner)
    digest = [[line.replace("<b>", "").replace("</b>", "")] for line in build(s, sp).splitlines() if line.strip()]
    summary = [["Показатель", "Значение"],
               ["Период", f"{r['start']} — {r['end']}"],
               ["Начислено, ₽", float(Decimal(r["revenue"]))],
               ["Поступило, ₽", float(Decimal(r["payments"]))],
               ["Результат парка, ₽", float(Decimal(r["profit"]))],
               ["Долг, ₽", float(Decimal(r["debt"]))],
               ["Загрузка, %", r["utilization"]],
               [""], ["Утренняя сводка"]] + digest
    signals = [["Правило", "Что", "Причина", "Что сделать"]] + [
        [x["label"], x["title"], x["reason"], x["action"]] for x in compute(s, owner, limit=200)]
    docs = [["Код", "Получен", "Источник", "Вид", "Статус", "Сумма, ₽", "От кого / имя"]]
    for d in s.scalars(select(Item).where(Item.space == sp.id, Item.kind == "inbox").order_by(Item.created)):
        v = d.data.get("values") or {}
        amount = v.get("amount") or v.get("total")
        docs.append([d.code, d.created.strftime("%d.%m.%Y %H:%M"), d.data.get("source", ""), d.data.get("kind") or "",
                     STATUS.get(d.data.get("status"), d.data.get("status", "")),
                     number(amount),
                     (d.data.get("mail") or {}).get("from") or d.data.get("name", "")])
    return {"Сводка": summary, "Сделать сейчас": signals, "Документы": docs}


def xlsx(data: dict[str, list[list]]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in data.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor="F1ECE2")
        ws.freeze_panes = "A2"
        if name != "Сводка" and ws.max_row > 1:
            ws.auto_filter.ref = ws.dimensions
        for col in ws.columns:
            width = max(len(str(c.value or "")) for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(60, max(10, width + 2))
            for c in col:
                if isinstance(c.value, float):
                    c.number_format = "# ##0"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def viewer(s, request):
    from .api import auth

    sp = auth(s, request)
    if sp.role not in VIEW:
        fail("Выгрузка доступна собственнику и финансисту", 403)
    return sp


@router.get("/api/v1/export.xlsx")
def export_xlsx(request: Request):
    with db() as s:
        body = xlsx(tables(s, viewer(s, request)))
    name = f"fleet-{datetime.now():%Y-%m-%d}.xlsx"
    return Response(body, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---------------------------------------------------------------- Google Sheets


def configured() -> bool:
    return bool(os.getenv("GOOGLE_SA_JSON") and os.getenv("GOOGLE_SHEET_ID"))


def token() -> str:
    from google.auth import crypt, jwt

    info = json.loads(open(os.environ["GOOGLE_SA_JSON"], encoding="utf-8").read())
    signer = crypt.RSASigner.from_service_account_info(info)
    t = int(time.time())
    assertion = jwt.encode(signer, {"iss": info["client_email"], "scope": SCOPE, "aud": info["token_uri"],
                                    "iat": t, "exp": t + 3600})
    r = httpx.post(info["token_uri"], data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                            "assertion": assertion}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


def mirror(data: dict[str, list[list]]) -> dict:
    sheet = os.environ["GOOGLE_SHEET_ID"]
    base = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet}"
    with httpx.Client(headers={"Authorization": "Bearer " + token()}, timeout=30) as c:
        have = {x["properties"]["title"] for x in c.get(base, params={"fields": "sheets.properties.title"}).raise_for_status().json()["sheets"]}
        missing = [n for n in data if n not in have]
        if missing:
            c.post(base + ":batchUpdate", json={"requests": [{"addSheet": {"properties": {"title": n}}} for n in missing]}).raise_for_status()
        c.post(base + "/values:batchClear", json={"ranges": [f"'{n}'" for n in data]}).raise_for_status()
        c.post(base + "/values:batchUpdate", json={"valueInputOption": "RAW", "data": [
            {"range": f"'{n}'!A1", "values": [[v if v != "" else None for v in row] for row in rows]} for n, rows in data.items()
        ]}).raise_for_status()
    return {"url": f"https://docs.google.com/spreadsheets/d/{sheet}", "sheets": {n: len(r) - 1 for n, r in data.items()}}


@router.get("/api/v1/export")
def export_view(request: Request):
    with db() as s:
        viewer(s, request)
    return {"sheets": configured(), "xlsx": "/api/v1/export.xlsx",
            "url": f"https://docs.google.com/spreadsheets/d/{os.environ['GOOGLE_SHEET_ID']}" if configured() else None}


@router.post("/api/v1/export/sheets")
def export_sheets(request: Request):
    if not configured():
        fail("Google Sheets не подключены: нужен сервисный аккаунт. Выгрузка в XLSX работает без него.", 409)
    with db() as s:
        data = tables(s, viewer(s, request))
    try:
        return {**mirror(data), "at": now().isoformat()}
    except httpx.HTTPError:
        fail("Google Sheets не приняли запись: проверьте, что таблица открыта сервисному аккаунту", 502)
