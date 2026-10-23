import os, json, secrets, hashlib, asyncio, io, csv, time
from datetime import timedelta, datetime
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, HTTPException, UploadFile, File
from fastapi.responses import (
    StreamingResponse,
    FileResponse,
    ORJSONResponse as JSONResponse,
)
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, func, text, delete, or_
from sqlalchemy.exc import IntegrityError
from psycopg.types.range import Range
from .db import (
    db,
    Space,
    Item,
    Entry,
    Event,
    Receipt,
    Job,
    Usage,
    System,
    Booking,
    AccessToken,
    FILES,
    URL,
    now,
    uid,
)
from .seed import claim_space, ROLES, BRANCHES, SOURCES, add
from .domain import (
    command,
    visible,
    get,
    cansee,
    serialize,
    fail,
    today,
    calendar,
    money,
    parse_date,
    READ,
    STAFF,
    file_access,
)
from .reports import report, entries, ledger_row, scope, payment_allocation

app = FastAPI(
    title="Taxi Fleet Concept",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)


class Cmd(BaseModel):
    action: str
    payload: dict = Field(default_factory=dict)


class Role(BaseModel):
    role: str


class AIInput(BaseModel):
    mode: str = "knowledge"
    prompt: str = Field(min_length=2, max_length=6000)
    target: str | None = None
    file: str | None = None


@app.middleware("http")
async def headers(request, call_next):
    if (
        request.method not in ("GET", "HEAD", "OPTIONS")
        and request.url.path != "/api/v1/telegram/webhook"
    ):
        origin = request.headers.get("origin")
        if origin and origin not in (
            URL,
            *filter(None, os.getenv("EXTRA_ORIGINS", "").split(",")),  # older domains of the same stand
            "http://127.0.0.1:3008",
            "http://localhost:5173",
        ):
            return JSONResponse({"detail": "Недопустимый источник запроса"}, 403)
    try:
        r = await call_next(request)
    except IntegrityError:
        return JSONResponse(
            {
                "detail": "Конфликт: объект уже существует или автомобиль занят в выбранный период."
            },
            409,
        )
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Referrer-Policy"] = "same-origin"
    r.headers["Cache-Control"] = "no-store"
    return r


def auth(s, request):
    token = request.cookies.get("fleet_session")
    if not token:
        fail("Начните личную демосессию", 401)
    digest = hashlib.sha256(token.encode()).hexdigest()
    query = select(Space).where(
        or_(
            Space.token == digest,
            Space.id.in_(
                select(AccessToken.space).where(
                    AccessToken.token == digest,
                    AccessToken.created > now() - timedelta(hours=24),
                )
            ),
        )
    )
    if request.method != "GET":
        query = query.with_for_update()
    sp = s.scalar(query)
    if not sp or sp.touched < now() - timedelta(hours=24):
        fail("Демосессия завершена", 401)
    if sp.data.get("tg_user") and request.url.path != "/api/v1/session" and (
        not sp.data.get("pd_consent") or not sp.data.get("tg_role_chosen")
    ):
        fail("Завершите онбординг в боте", 403)
    if request.method != "GET" or sp.touched < now() - timedelta(minutes=5):
        sp.touched = now()
    return sp


def space_data(sp):
    return {
        "id": sp.id,
        "role": sp.role,
        "roles": ROLES,
        "principals": sp.data,
        "expires": (sp.touched + timedelta(hours=24)).isoformat(),
    }


def set_cookie(response, token):
    response.set_cookie(
        "fleet_session",
        token,
        httponly=True,
        secure=URL.startswith("https"),
        samesite="lax",
        max_age=86400,
        path="/",
    )


@app.get("/api/health")
def health():
    with db() as s:
        s.execute(text("SELECT 1"))
        worker = s.get(System, "worker")
        age = (
            (now() - datetime.fromisoformat(worker.data["heartbeat"])).total_seconds()
            if worker
            else None
        )
        pending = s.scalar(
            select(func.count()).select_from(Job).where(Job.state == "pending")
        )
        return {
            "status": "ok" if age is not None and age < 90 else "degraded",
            "database": "ok",
            "worker_age_seconds": age,
            "pending": pending,
            "telegram": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
            "telegram_username": (
                os.getenv("TELEGRAM_USERNAME")
                if os.getenv("TELEGRAM_BOT_TOKEN")
                else None
            ),
            "ai": bool(
                os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENROUTER_API_KEY")
            ),
        }


@app.post("/api/v1/session")
def session(request: Request, response: Response):
    with db() as s:
        # Bound public creation globally, without retaining raw visitor IPs.
        s.execute(text("SELECT pg_advisory_xact_lock(684411)"))
        if (
            s.scalar(
                select(func.count())
                .select_from(Space)
                .where(
                    Space.created > now() - timedelta(minutes=1),
                    ~Space.data.has_key("pool"),
                )
            )
            >= 8
        ):
            fail("Подождите минуту перед созданием новой сессии", 429)
        sp = claim_space(s)
        token = secrets.token_urlsafe(32)
        sp.token = hashlib.sha256(token.encode()).hexdigest()
        set_cookie(response, token)
        return space_data(sp)


@app.get("/api/v1/session")
def me(request: Request):
    with db() as s:
        return space_data(auth(s, request))


@app.post("/api/v1/session/role")
def role(body: Role, request: Request):
    if body.role not in ROLES:
        fail("Неизвестная роль")
    with db() as s:
        sp = auth(s, request)
        sp.role = body.role
        return space_data(sp)


@app.post("/api/v1/session/reset")
def reset(request: Request, response: Response):
    with db() as s:
        sp = auth(s, request)
        old_id = sp.id
        s.delete(sp)
        s.flush()
        s.add(Job(kind="cleanup_files", data={"space": old_id}, result={}))
        sp = claim_space(s)
        token = secrets.token_urlsafe(32)
        sp.token = hashlib.sha256(token.encode()).hexdigest()
        set_cookie(response, token)
        return space_data(sp)


@app.get("/api/v1/bootstrap")
def bootstrap(request: Request):
    with db() as s:
        sp = auth(s, request)
        kinds = [
            "vehicle",
            "client",
            "contract",
            "ticket",
            "investor",
            "statement",
            "tariff",
            "referral",
            "inspection",
            "import",
            "knowledge",
            "document",
        ]
        items = s.scalars(
            select(Item)
            .where(Item.space == sp.id, Item.kind.in_(kinds))
            .order_by(Item.code)
        ).all()
        owned = (
            {
                x.id
                for x in items
                if x.kind == "vehicle"
                and x.data.get("investor") == sp.data.get("investor")
            }
            if sp.role == "investor"
            else {
                x.data["vehicle"]
                for x in items
                if x.kind == "contract" and x.data.get("client") == sp.data.get(sp.role)
            }
        )

        def allowed(x):
            if sp.role in ("owner", "admin"):
                return True
            if sp.role in READ:
                return x.kind in READ[sp.role]
            if x.kind == "vehicle":
                return (
                    x.id in owned
                    or sp.role == "client"
                    and x.data["direction"] in ("rental", "commercial")
                )
            if x.kind == "contract":
                return (
                    x.data["vehicle"] in owned
                    if sp.role == "investor"
                    else x.data["client"] == sp.data.get(sp.role)
                )
            if x.kind in ("ticket", "document", "inspection"):
                return x.data.get("vehicle") in owned
            if x.kind == "client":
                return x.id == sp.data.get(sp.role)
            if x.kind in ("statement", "investor"):
                return sp.role == "investor" and (
                    x.id if x.kind == "investor" else x.data.get("investor")
                ) == sp.data.get("investor")
            if x.kind == "referral":
                return sp.role == "driver" and x.data.get("client") == sp.data.get(
                    "driver"
                )
            if x.kind == "knowledge":
                return sp.role in x.data.get("roles", [])
            return x.kind == "tariff"

        result = {k: [] for k in kinds}
        for x in items:
            if allowed(x):
                result[x.kind].append(serialize(x))
        if sp.role == "service":
            result["client"] = []
        if sp.role == "screening":
            for k in ("statement", "import", "investor"):
                result[k] = []
        bookings = s.scalars(
            select(Booking).where(
                Booking.space == sp.id,
                Booking.state.in_(["active", "confirmed", "hold"]),
            )
        ).all()
        ids = {x["id"] for x in result["vehicle"]}
        result["bookings"] = [
            {
                "id": b.id,
                "vehicle": b.vehicle,
                "contract": (
                    b.contract
                    if sp.role in ("owner", "admin", "manager", "finance")
                    else None
                ),
                "start": b.period.lower.isoformat(),
                "end": b.period.upper.isoformat(),
                "state": b.state,
                "expires": b.expires.isoformat() if b.expires else None,
            }
            for b in bookings
            if b.vehicle in ids and (b.expires is None or b.expires > now())
        ]
        result.update(
            session=space_data(sp),
            branches=BRANCHES,
            sources=SOURCES,
            today=str(today()),
            telegram_username=os.getenv("TELEGRAM_USERNAME"),
            ai_configured=bool(
                os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENROUTER_API_KEY")
            ),
        )
        return JSONResponse(result)


@app.get("/api/v1/report")
def reports(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    branch: str | None = None,
    direction: str | None = None,
):
    if start:
        parse_date(start)
    if end:
        parse_date(end)
    with db() as s:
        return JSONResponse(report(s, auth(s, request), start, end, branch, direction))


@app.get("/api/v1/availability")
def availability(request: Request, start: str, end: str, direction: str | None = None):
    from .domain import day_range

    day_range(start, end)
    if end <= start:
        fail("Окончание должно быть позже начала")
    period = Range(
        datetime.fromisoformat(start + "T10:00:00+03:00"),
        datetime.fromisoformat(end + "T10:00:00+03:00"),
        "[)",
    )
    with db() as s:
        sp = auth(s, request)
        cars = visible(s, sp, "vehicle")
        occupied = set(
            s.scalars(
                select(Booking.vehicle).where(
                    Booking.space == sp.id,
                    Booking.period.overlaps(period),
                    Booking.state.in_(["active", "confirmed", "hold"]),
                    ((Booking.expires == None) | (Booking.expires > now())),
                )
            ).all()
        )
        return {
            "start": start,
            "end": end,
            "items": [
                {
                    "id": v.id,
                    "model": v.data["model"],
                    "code": v.code,
                    "available": v.id not in occupied and v.data["status"] == "ready",
                    "reason": (
                        "Автомобиль занят"
                        if v.id in occupied
                        else (
                            "Нужна подготовка"
                            if v.data["status"] != "ready"
                            else "Доступен"
                        )
                    ),
                    "rate": v.data["rate"],
                }
                for v in cars
                if not direction or v.data["direction"] == direction
            ],
        }


@app.get("/api/v1/ledger")
def ledger(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    vehicle: str | None = None,
    contract: str | None = None,
    offset: int = 0,
):
    with db() as s:
        sp = auth(s, request)
        q = scope(s, sp)
        if start:
            q = q.where(Entry.date >= str(parse_date(start)))
        if end:
            q = q.where(Entry.date <= str(parse_date(end)))
        if vehicle:
            q = q.where(Entry.vehicle == vehicle)
        if contract:
            q = q.where(Entry.contract == contract)
        total = s.scalar(select(func.count()).select_from(q.subquery()))
        rows = s.scalars(
            q.order_by(Entry.date.desc(), Entry.id).offset(max(0, offset)).limit(200)
        ).all()
        return JSONResponse({"total": total, "rows": [ledger_row(e) for e in rows]})


@app.get("/api/v1/items/{id}")
def detail(id: str, request: Request):
    with db() as s:
        sp = auth(s, request)
        x = get(s, sp, id)
        if not cansee(s, sp, x):
            fail("Недостаточно прав", 403)
        r = serialize(x)
        if x.kind == "contract":
            r["calendar"] = calendar(x)
            r["ledger"] = [
                ledger_row(e) for e in entries(s, sp, contract=id, limit=300)
            ]
            r["allocation"] = payment_allocation(s, sp, id)
        if x.kind == "vehicle":
            r["contracts"] = [
                serialize(c)
                for c in visible(s, sp, "contract")
                if c.data["vehicle"] == id
            ]
            r["tickets"] = [
                serialize(t)
                for t in visible(s, sp, "ticket")
                if t.data["vehicle"] == id
            ]
            r["ledger"] = [ledger_row(e) for e in entries(s, sp, vehicle=id, limit=300)]
        r["events"] = [
            {"id": e.id, "title": e.title, "role": e.role, "at": e.created.isoformat()}
            for e in s.scalars(
                select(Event)
                .where(Event.space == sp.id, Event.target == id)
                .order_by(Event.id.desc())
                .limit(100)
            )
        ]
        return JSONResponse(r)


@app.post("/api/v1/commands")
def cmd(body: Cmd, request: Request):
    with db() as s:
        return command(
            s,
            auth(s, request),
            body.action,
            body.payload,
            request.headers.get("idempotency-key", ""),
        )


@app.get("/api/v1/events")
async def events(request: Request):
    with db() as s:
        sp = auth(s, request)
        sid = sp.id
        role = sp.role
        allowed = {
            x.id
            for kind in ("vehicle", "contract", "ticket", "client", "statement")
            for x in visible(s, sp, kind)
        }
    try:
        last = int(request.headers.get("last-event-id", "0"))
    except ValueError:
        last = 0

    async def stream():
        nonlocal last
        for _ in range(15):
            if await request.is_disconnected():
                break
            with db() as s:
                current = s.get(Space, sid)
                if not current or current.role != role:
                    break
                rows = s.scalars(
                    select(Event)
                    .where(Event.space == sid, Event.id > last)
                    .order_by(Event.id)
                    .limit(100)
                ).all()
                permitted = set()
                for e in rows:
                    if role in ("owner", "admin", "finance"):
                        permitted.add(e.id)
                    elif e.target:
                        target = s.scalar(
                            select(Item).where(Item.space == sid, Item.id == e.target)
                        )
                        if target and cansee(s, current, target):
                            permitted.add(e.id)
            for e in rows:
                last = e.id
                if e.id in permitted:
                    yield f"id: {e.id}\ndata: " + json.dumps(
                        {
                            "title": e.title,
                            "target": e.target,
                            "role": e.role,
                            "at": e.created.isoformat(),
                        },
                        ensure_ascii=False,
                    ) + "\n\n"
            yield ": keepalive\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
    )


@app.post("/api/v1/files")
async def upload(request: Request, file: UploadFile = File(...)):
    raw = await file.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        fail("Максимум 8 МБ")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".pdf", ".csv", ".xlsx"):
        fail("Поддерживаются PNG, JPEG, PDF, CSV, XLSX")
    if ext in (".png", ".jpg", ".jpeg"):
        from PIL import Image

        try:
            im = Image.open(io.BytesIO(raw))
            im.verify()
        except Exception:
            fail("Некорректное изображение")
    if ext == ".pdf" and not raw.startswith(b"%PDF-"):
        fail("Некорректный PDF")
    if ext == ".xlsx":
        import zipfile

        try:
            z = zipfile.ZipFile(io.BytesIO(raw))
            if sum(x.file_size for x in z.infolist()) > 30 * 1024 * 1024 or any(
                "vbaproject" in n.lower() for n in z.namelist()
            ):
                fail("Слишком большой XLSX или макросы")
        except zipfile.BadZipFile:
            fail("Некорректный XLSX")
    with db() as s:
        sp = auth(s, request)
        total = s.scalar(
            select(func.count())
            .select_from(Item)
            .where(Item.space == sp.id, Item.kind == "file")
        )
        if total >= 30:
            fail("Лимит 30 файлов на сессию", 429)
        x = add(
            s,
            sp.id,
            "file",
            "F-" + uid()[:8],
            {
                "name": Path(file.filename or "file").name[:120],
                "ext": ext,
                "size": len(raw),
                "creator_role": sp.role,
            },
        )
        path = FILES / sp.id
        path.mkdir(parents=True, exist_ok=True)
        (path / (x.id + ext)).write_bytes(raw)
        return serialize(x)


@app.get("/api/v1/files/{id}")
def download(id: str, request: Request):
    with db() as s:
        sp = auth(s, request)
        x = get(s, sp, id, "file")
        if not file_access(s, sp, x):
            fail("Недостаточно прав", 403)
        path = FILES / sp.id / (x.id + x.data["ext"])
        if not path.exists():
            fail("Файл недоступен", 404)
        return FileResponse(
            path, filename=x.data["name"], headers={"Content-Disposition": "attachment"}
        )


@app.post("/api/v1/import/preview")
def import_preview(body: dict, request: Request):
    with db() as s:
        sp = auth(s, request)
        if sp.role not in ("owner", "finance", "admin"):
            fail("Недостаточно прав", 403)
        x = get(s, sp, body.get("file"), "file")
        raw = (FILES / sp.id / (x.id + x.data["ext"])).read_bytes()
        if x.data["ext"] == ".csv":
            try:
                rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
            except UnicodeDecodeError:
                fail("Нужен CSV UTF-8")
        elif x.data["ext"] == ".xlsx":
            from openpyxl import load_workbook

            w = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
            it = iter(w.active.values)
            headers = next(it, [])
            rows = [dict(zip(headers, row)) for row in it]
            w.close()
        else:
            fail("Импорт принимает CSV или XLSX")
        if len(rows) > 1000:
            fail("Не более 1000 строк за импорт")
        seen = set()
        out = []
        for i, row in enumerate(rows):
            row = {str(k): str(v) if v is not None else "" for k, v in row.items()}
            r = {k: row.get(k, "") for k in ("reference", "contract", "date", "amount")}
            try:
                if not r["reference"] or len(r["reference"]) > 100:
                    raise ValueError("Нет уникального номера операции")
                if r["reference"] in seen:
                    raise ValueError("Повтор номера внутри файла")
                seen.add(r["reference"])
                parse_date(r["date"])
                r["amount"] = str(money(r["amount"]))
                if money(r["amount"]) <= 0:
                    raise ValueError("Сумма должна быть положительной")
                if not s.scalar(
                    select(Item.id).where(
                        Item.space == sp.id,
                        Item.kind == "contract",
                        Item.code == r["contract"],
                    )
                ):
                    raise ValueError("Договор не найден")
            except (ValueError, HTTPException) as e:
                r["error"] = str(e.detail if isinstance(e, HTTPException) else e)
            out.append(r)
        item = add(
            s,
            sp.id,
            "import",
            "IMP-" + uid()[:6],
            {
                "status": "preview",
                "rows": out,
                "name": x.data["name"],
                "posted": 0,
                "unmatched": [],
            },
        )
        return serialize(item)


@app.get("/api/v1/import/sample")
def sample(request: Request):
    with db() as s:
        sp = auth(s, request)
        cs = visible(s, sp, "contract")[:4]
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["reference", "contract", "date", "amount"])
        for i, c in enumerate(cs):
            w.writerow([f"DEMO-BANK-{i+1}", c.code, str(today()), 2500 + i * 100])
        w.writerow(["DEMO-BANK-5", "НЕИЗВЕСТНЫЙ", str(today()), 1200])
        return Response(
            "\ufeff" + out.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="bank-demo.csv"'},
        )


@app.get("/api/v1/documents/{id}")
def document(id: str, request: Request, format: str = "pdf"):
    if format not in ("pdf", "xlsx"):
        fail("Поддерживаются PDF и XLSX")
    from .documents import render

    with db() as s:
        sp = auth(s, request)
        x = get(s, sp, id)
        if not cansee(s, sp, x):
            fail("Недостаточно прав", 403)
        if x.kind not in ("contract", "statement", "ticket", "vehicle", "inspection"):
            fail("Для объекта нет документа")
        data = render(s, sp, x, format)
        return Response(
            data,
            media_type=(
                "application/pdf"
                if format == "pdf"
                else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            headers={
                "Content-Disposition": f'attachment; filename="park-{x.code.replace(":","-")}.{format}"'
            },
        )


@app.post("/api/v1/ai")
def ai(body: AIInput, request: Request):
    with db() as s:
        sp = auth(s, request)
        if body.mode not in (
            "knowledge",
            "ticket",
            "finance",
            "document",
            "agent",
            "rag",
        ):
            fail("Неизвестная функция")
        if body.mode == "finance" and sp.role not in (
            "owner",
            "finance",
            "admin",
            "investor",
            "driver",
            "client",
        ):
            fail("Нет доступа к финансовым данным", 403)
        if body.target:
            x = get(s, sp, body.target)
            if not cansee(s, sp, x):
                fail("Недостаточно прав", 403)
        if body.file:
            f = get(s, sp, body.file, "file")
            if not file_access(s, sp, f):
                fail("Нет доступа к файлу", 403)
        if (
            s.scalar(
                select(func.count())
                .select_from(Job)
                .where(
                    Job.space == sp.id,
                    Job.kind == "ai",
                    Job.due > now() - timedelta(hours=1),
                )
            )
            >= 10
        ):
            fail("Лимит 10 AI-запросов в час", 429)
        j = Job(
            id=uid(),
            space=sp.id,
            kind="ai",
            data={**body.model_dump(), "role": sp.role},
            result={},
        )
        s.add(j)
        return {"id": j.id, "state": "pending"}


@app.get("/api/v1/jobs/{id}")
def job(id: str, request: Request):
    with db() as s:
        sp = auth(s, request)
        j = s.scalar(select(Job).where(Job.space == sp.id, Job.id == id))
        if not j or j.data.get("role") != sp.role:
            fail("Задание не найдено", 404)
        return {"id": j.id, "state": j.state, "result": j.result}


@app.get("/api/v1/settings")
def settings(request: Request):
    with db() as s:
        sp = auth(s, request)
        if sp.role not in ("admin", "owner", "finance"):
            fail("Недостаточно прав", 403)
        usage = s.scalars(select(Usage).where(Usage.space == sp.id)).all()
        quality = s.get(System, "quality")
        return {
            "usage": [
                {
                    "model": u.model,
                    "cost": str(u.cost),
                    "tokens": u.tokens,
                    "ms": u.ms,
                    "at": u.created.isoformat(),
                }
                for u in usage
            ],
            "budget": "0.50",
            "quality": quality.data if quality else None,
            "telegram": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
            "ai": bool(
                os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENROUTER_API_KEY")
            ),
            "closed_months": sp.data.get("closed_months", []),
        }


@app.post("/api/v1/telegram/link")
def telegram_link(request: Request):
    with db() as s:
        sp = auth(s, request)
        username = os.getenv("TELEGRAM_USERNAME")
        if not username:
            fail("Ожидается подключение отдельного Telegram-бота", 503)
        token = secrets.token_urlsafe(20)
        sp.data = {
            **sp.data,
            "tg_link_hash": hashlib.sha256(token.encode()).hexdigest(),
            "tg_link_expires": (now() + timedelta(minutes=10)).isoformat(),
        }
        return {"url": f"https://t.me/{username}?start={token}"}


@app.post("/api/v1/telegram/webhook")
async def telegram_webhook(request: Request):
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    if not secret or not secrets.compare_digest(
        request.headers.get("x-telegram-bot-api-secret-token", ""), secret
    ):
        fail("Недопустимый webhook", 403)
    data = await request.json()
    with db() as s:
        key = "tg:" + str(data.get("update_id"))
        if s.get(System, key):
            return {"ok": True}
        s.add(System(key=key, data={"received": now().isoformat()}))
        s.add(Job(kind="telegram", data=data, result={}))
    return {"ok": True}


class BotSim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str | None = Field(default=None, max_length=1500)
    callback: str | None = Field(default=None, max_length=64)
    message_id: str | None = Field(default=None, max_length=80)
    # «Поделиться номером»: в эмуляторе своим номером считается номер демо-водителя из учёта
    contact: bool = False


@app.post("/api/v1/bot/sim")
def bot_sim(body: BotSim, request: Request):
    """Веб-эмулятор бота: апдейт в формате Telegram идёт в ту же очередь и ту же логику
    (telegram.handle), но ответ возвращается в браузер, а не в Telegram."""
    if not (body.text or "").strip() and not body.callback and not body.contact:
        fail("Пустое сообщение")
    with db() as s:
        sp = auth(s, request)
        recent = s.scalar(
            select(func.count())
            .select_from(Job)
            .where(
                Job.space == sp.id,
                Job.kind == "telegram_sim",
                Job.due > now() - timedelta(minutes=1),
            )
        )
        if recent >= 20:
            fail("Не так быстро: не больше 20 сообщений в минуту", 429)
        update_id = "sim-" + secrets.token_hex(6)
        who = {"id": "web:" + sp.id, "first_name": "Гость демо"}
        chat = {"id": 0, "type": "private"}
        if body.contact:
            person = s.get(Item, sp.data.get("driver", ""))
            phone = (person.data.get("phone") if person else "") or "+7 (000) 000-0000"
            update = {
                "update_id": update_id,
                "message": {
                    "from": who,
                    "chat": chat,
                    "contact": {
                        "phone_number": phone,
                        "user_id": who["id"],
                        "first_name": who["first_name"],
                    },
                },
            }
        else:
            update = (
                {
                    "update_id": update_id,
                    "callback_query": {
                        "id": update_id,
                        "from": who,
                        "message": {"chat": chat, "message_id": body.message_id},
                        "data": body.callback,
                    },
                }
                if body.callback
                else {
                    "update_id": update_id,
                    "message": {"from": who, "chat": chat, "text": body.text.strip()},
                }
            )
        j = Job(
            kind="telegram_sim",
            space=sp.id,
            data={
                "update": update,
                "space": sp.id,
                "role": sp.role,
                "prompt": "Эмулятор бота: "
                + (
                    "поделился номером"
                    if body.contact
                    else (
                        body.text.strip()[:100]
                        if body.text
                        else "кнопка " + body.callback
                    )
                ),
            },
            result={},
        )
        s.add(j)
        s.flush()
        return {"id": j.id}


@app.get("/api/v1/bot/sim/{id}")
def bot_sim_result(id: str, request: Request):
    # без проверки роли: выбор роли в самом чате меняет роль сессии
    with db() as s:
        sp = auth(s, request)
        j = s.scalar(
            select(Job).where(
                Job.space == sp.id, Job.id == id, Job.kind == "telegram_sim"
            )
        )
        if not j:
            fail("Сообщение не найдено", 404)
        return {"state": j.state, "result": j.result}


@app.post("/api/v1/telegram/auth")
def telegram_auth(body: dict, response: Response):
    from .telegram import validate

    data = validate(body.get("initData", ""))
    with db() as s:
        s.execute(text("SELECT pg_advisory_xact_lock(hashtext(:id))"), {"id": "telegram:" + str(data["id"])})
        sp = s.scalar(
            select(Space).where(Space.data["tg_user"].astext == str(data["id"]))
        )
        if not sp:
            sp = claim_space(s)
            sp.role = "driver"
            sp.data = {**sp.data, "tg_user": str(data["id"])}
        if not sp.data.get("pd_consent") or not sp.data.get("tg_role_chosen"):
            response.delete_cookie("fleet_session", path="/")
            return {"onboarding_required": True, "telegram_username": os.getenv("TELEGRAM_USERNAME")}
        token = secrets.token_urlsafe(32)
        s.add(
            AccessToken(token=hashlib.sha256(token.encode()).hexdigest(), space=sp.id)
        )
        sp.touched = now()
        set_cookie(response, token)
        return space_data(sp)


@app.post("/api/v1/rental/quote")
def rental_price(body: dict, request: Request):
    from .miniapp import rental_quote
    with db() as s:
        return rental_quote(s, auth(s, request), body)


@app.get("/api/v1/miniapp/state")
def miniapp_state(request: Request):
    from .miniapp import balance, fines
    with db() as s:
        sp = auth(s, request)
        if sp.role not in ("driver", "client"):
            return {"role": sp.role, "web_cabinet": True}
        if not sp.data.get("pd_consent") or not sp.data.get("tg_role_chosen"):
            return {"role": sp.role, "onboarding_required": True}
        contracts = []
        for c in visible(s, sp, "contract"):
            charged = balance(s, sp, c.id, ["charge"])
            paid = balance(s, sp, c.id, ["payment"])
            dep = balance(s, sp, c.id, ["deposit", "deposit_release"])
            b = s.scalar(select(Booking).where(Booking.space == sp.id, Booking.contract == c.id))
            contracts.append({"id": c.id, "charged": str(money(charged)), "paid": str(money(paid)),
                "debt": str(money(max(0, charged - paid))), "deposit_paid": str(money(dep)),
                "deposit_due": str(money(max(0, money(c.data.get("deposit", 0)) - dep))),
                "hold_expires": b.expires.isoformat() if b and b.expires else None,
                "upcoming": calendar(c, start=str(today()), end=str(min(parse_date(c.data["end"]), today() + timedelta(days=6))))
                    if c.data["status"] == "active" and parse_date(c.data["end"]) >= today() else [],
                "booking_state": b.state if b else None})
        receipts = s.scalars(select(Item).where(Item.space == sp.id, Item.kind == "demo_payment",
            Item.data["client"].astext == sp.data.get(sp.role)).order_by(Item.created.desc())).all()
        return {"role": sp.role, "contracts": contracts, "fines": fines(s, sp) if sp.role == "driver" else [],
                "receipts": [serialize(x) for x in receipts]}


@app.get("/api/v1/miniapp/receipts/{id}")
def demo_receipt(id: str, request: Request):
    from html import escape
    from weasyprint import HTML
    with db() as s:
        sp = auth(s, request)
        x = get(s, sp, id, "demo_payment")
        if not cansee(s, sp, x) or x.data.get("status") != "paid":
            fail("Квитанция недоступна", 403)
        d = x.data
        content = f'''<html lang="ru"><meta charset="utf-8"><style>
        body{{font:15px sans-serif;color:#202328;padding:30px}}h1{{font-size:30px}}
        small{{color:#676b75}}.amount{{font-size:40px;margin:32px 0}}</style>
        <h1>Учебный таксопарк</h1><h2>Учебная квитанция {escape(x.code)}</h2>
        <p>{escape(d['label'])}</p><div class="amount">{escape(d['amount'])} ₽</div>
        <p>Дата: {escape(d['paid_at'])}</p><p>Операция: {escape(x.id)}</p>
        <small>Тестовая операция. Реального списания не было. Не является фискальным чеком.
        Независимый концепт · Игорь Шварёв.</small></html>'''
        pdf = HTML(string=content).write_pdf()
        return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{x.code}.pdf"'})


@app.post("/api/v1/miniapp/fines/sync")
def miniapp_sync_fines(request: Request):
    from .integrations import enqueue
    with db() as s:
        sp = auth(s, request)
        if sp.role != "driver" or not sp.data.get("pd_consent") or not sp.data.get("tg_role_chosen"):
            fail("Завершите вход водителя в боте", 403)
        pending = s.scalar(select(Job).where(Job.space == sp.id, Job.kind == "integration",
            Job.state.in_(["pending", "running"]), Job.data["context"]["source"].astext == "fines"))
        if pending:
            return {"id": pending.data["context"]["run"], "status": "queued"}
        recent = s.scalar(select(func.count()).select_from(Job).where(Job.space == sp.id,
            Job.kind == "integration", Job.data["context"]["source"].astext == "fines",
            Job.due > now() - timedelta(minutes=1)))
        if recent >= 5:
            fail("Не более пяти обновлений штрафов в минуту", 429)
        job = enqueue(s, sp, "fines")
        return {"id": job["run"], "status": "queued"}


from .under import router as under_router

app.include_router(under_router)
from .integrations import router as integration_router

app.include_router(integration_router)
from .inbox import router as inbox_router

app.include_router(inbox_router)
from .crm import router as crm_router

app.include_router(crm_router)
