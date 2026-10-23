"""Telegram-бот таксопарка: три типа пользователей (водитель, клиент, сотрудник отдела) в одном боте.

Вебхук (api.py) только проверяет secret_token, отсекает повторы по update_id и ставит задание в очередь;
здесь воркер разбирает апдейт, выполняет действие через те же бизнес-команды, что и веб-кабинет
(domain.command — роли, статусы, ключ идемпотентности), и отправляет ответ.
"""

import base64
import asyncio
import hashlib
import hmac
import html
import io
import json
import os
import re
import time
from datetime import datetime, timedelta
from functools import lru_cache
from urllib.parse import parse_qsl
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)
from fastapi import HTTPException
from sqlalchemy import select, func, text as sqltext

from psycopg.types.range import Range

from .db import FILES, ROOT, URL, Booking, Item, Space, Job, Event, Receipt, db, now
from .domain import command, fail, get, today, visible
from .reports import report
from .seed import claim_space

ROLES = {
    "driver": "Водитель",
    "client": "Клиент проката",
    "manager": "Менеджер парка",
    "service": "Сервис",
    "finance": "Финансы",
    "owner": "Собственник бизнеса",
}
STAFF_ROLES = ("manager", "service", "finance")
MSK = ZoneInfo("Europe/Moscow")
DISCLAIMER = "Концепт и прототип · данные учебные, это не бот реальной компании."


def validate(raw):
    """Проверка подписи initData Telegram Mini App."""
    pairs = dict(parse_qsl(raw, keep_blank_values=True))
    received = pairs.pop("hash", "")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        fail("Telegram не подключён", 503)
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    expected = hmac.new(
        secret,
        "\n".join(f"{k}={v}" for k, v in sorted(pairs.items())).encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, received):
        fail("Некорректная подпись Telegram", 403)
    try:
        age = time.time() - int(pairs.get("auth_date", "0"))
        user = json.loads(pairs["user"])
        if not isinstance(user, dict) or not isinstance(user.get("id"), int):
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        fail("Некорректные данные Telegram", 403)
    if age < -30 or age > 600:
        fail("Данные Telegram устарели", 403)
    return user


# ───────────────────────── отправка ─────────────────────────


def rub(v) -> str:
    return f"{int(float(v or 0)):,}".replace(",", " ") + " ₽"


def esc(v) -> str:
    return html.escape(str(v or ""))


def kb(*rows):
    """Строки кнопок: ("Текст", "callback") | ("Текст", "url:https://…") | ("Текст", "app")."""
    out = []
    for row in rows:
        buttons = []
        for text, action in row:
            if action == "app" or action.startswith("app:"):
                buttons.append(
                    InlineKeyboardButton(text=text, web_app=WebAppInfo(url=URL + "/?tg=1" + ("#tg/" + action[4:] if action.startswith("app:") else "")))
                )
            elif action == "web":
                buttons.append(InlineKeyboardButton(text=text, web_app=WebAppInfo(url=URL + "/?web=1")))
            elif action.startswith("url:"):
                buttons.append(InlineKeyboardButton(text=text, url=action[4:]))
            else:
                buttons.append(
                    InlineKeyboardButton(text=text, callback_data=action[:64])
                )
        out.append(buttons)
    return InlineKeyboardMarkup(inline_keyboard=out)


@lru_cache(maxsize=32)
def car_jpeg(image_path: str) -> bytes | None:
    """Фото модели из статики фронтенда → JPEG (sendPhoto надёжно принимает JPEG/PNG)."""
    from PIL import Image

    for base in (ROOT / "dist", ROOT / "public"):
        f = base / image_path.lstrip("/")
        if f.exists():
            out = io.BytesIO()
            Image.open(f).convert("RGB").save(out, "JPEG", quality=85)
            return out.getvalue()
    return None


async def _deliver(chat, messages, callback_id=None):
    bot = Bot(os.environ["TELEGRAM_BOT_TOKEN"])
    try:
        if callback_id:
            try:
                await bot.answer_callback_query(callback_id)
            except TelegramBadRequest:
                pass  # an expired callback must not lose the business result
        delivered = []
        for m in messages:
            markup = m.get("kb")
            if m.get("reply") == "contact":
                # запрос номера возможен только reply-клавиатурой, не inline
                markup = ReplyKeyboardMarkup(
                    keyboard=[
                        [
                            KeyboardButton(
                                text="📱 Поделиться номером", request_contact=True
                            )
                        ]
                    ],
                    resize_keyboard=True,
                    one_time_keyboard=True,
                )
            elif m.get("reply") == "remove":
                markup = ReplyKeyboardRemove()
            if m.get("photo"):
                raw = car_jpeg(m["photo"])
                if raw:
                    sent = await bot.send_photo(
                        chat,
                        BufferedInputFile(raw, "car.jpg"),
                        caption=m["text"][:1000],
                        parse_mode="HTML",
                        reply_markup=markup,
                    )
                    delivered.append(sent.message_id)
                    continue
            if m.get("document"):
                raw, name = m["document"]
                sent = await bot.send_document(
                    chat,
                    BufferedInputFile(raw, filename=name),
                    caption=m["text"][:1000],
                )
                delivered.append(sent.message_id)
                continue
            if m.get("edit_target") and not m.get("reply"):
                try:
                    sent = await bot.edit_message_text(chat_id=chat, message_id=int(m["edit_target"]),
                        text=m["text"][:4000], parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)
                    delivered.append(m["edit_target"])
                    continue
                except TelegramBadRequest as exc:
                    if "message is not modified" in str(exc):
                        delivered.append(m["edit_target"])
                        continue
                    # Deleted messages and photo captions need a fresh text bubble.
            sent = await bot.send_message(
                chat,
                m["text"][:4000],
                parse_mode="HTML",
                reply_markup=markup,
                disable_web_page_preview=True,
            )
            delivered.append(sent.message_id)
        return delivered
    finally:
        await bot.session.close()


async def send(chat, text, route=None):
    """Уведомление из воркера (события пространства)."""
    action = "web" if route == "web" else "app:" + route if route else "app"
    await _deliver(chat, [{"text": esc(text), "kb": kb([("Открыть кабинет", action)])}])


async def photo_bytes(file_id):
    bot = Bot(os.environ["TELEGRAM_BOT_TOKEN"])
    try:
        f = await bot.get_file(file_id)
        if (f.file_size or 0) > 8 * 1024 * 1024:
            raise ValueError("Фотография больше 8 МБ")
        out = io.BytesIO()
        await bot.download_file(f.file_path, destination=out)
        return out.getvalue()
    finally:
        await bot.session.close()


# ───────────────────────── меню по ролям ─────────────────────────


def role_picker(prefix=""):
    return {
        "text": prefix
        + "Кто вы? Бот один, а возможности у каждого свои — как в настоящем парке.\n\n"
        + f"<i>{DISCLAIMER}</i>",
        "kb": kb(
            [("🚕 Я водитель", "role:driver"), ("🔑 Я клиент проката", "role:client")],
            [("🧰 Я сотрудник парка", "staff")],
            [("📊 Я собственник бизнеса", "role:owner")],
        ),
    }


def staff_picker():
    return {
        "text": "Какой отдел? У каждого свои права: менеджер подтверждает брони, сервис ведёт ремонт, "
        "финансы согласуют деньги.",
        "kb": kb(
            [
                ("Менеджер парка", "role:manager"),
                ("Сервис", "role:service"),
                ("Финансы", "role:finance"),
            ],
            [("← Назад", "roles")],
        ),
    }


# ───────────────────────── ПДн и онбординг ─────────────────────────
# Демо: согласие (152-ФЗ) → «Поделиться номером» → роль из учёта; сотрудники — по коду.
# Номер не храним в открытом виде: только солёный хеш и маска для показа.

PD_VERSION = "2026-10-demo"
INVITES = {
    "MANAGER-2026": "manager",
    "SERVICE-2026": "service",
    "FINANCE-2026": "finance",
}


def consent_msg():
    return {
        "text": "Здравствуйте! Это бот таксопарка: водители, клиенты проката и сотрудники отделов.\n\n"
        "<b>Согласие на обработку персональных данных</b> (152-ФЗ). Чтобы определить вашу роль и связываться "
        "по заявкам, бот обрабатывает: Telegram ID, номер телефона (только по вашей кнопке «Поделиться»), "
        "сообщения и фото по заявкам. Цель — работа с договором и обращениями; срок — до отзыва согласия. "
        "Отозвать и удалить данные: /delete_me. Посмотреть, что хранится: /privacy.\n\n"
        f"<i>{DISCLAIMER}</i>",
        "kb": kb([("✅ Согласен", "pd:yes"), ("✖ Не согласен", "pd:no")]),
    }


def identify_msgs():
    return [
        {
            "text": "Спасибо. Поделитесь номером — найду вас в учёте парка и открою нужное меню.",
            "reply": "contact",
        },
        {
            "text": "Или другой способ:",
            "kb": kb(
                [("🧰 Я сотрудник — ввести код", "id:staff")],
                [("🎭 Демо: выбрать роль вручную", "roles")],
            ),
        },
    ]


def digits(phone):
    return re.sub(r"\D", "", phone or "")


def mask_phone(phone):
    d = digits(phone)
    return f"+{d[:1]} *** ***-{d[-4:-2]}-{d[-2:]}" if len(d) >= 6 else "—"


def phone_hash(sp, phone):
    return hashlib.sha256(f"phone:{sp.id}:{digits(phone)}".encode()).hexdigest()


def privacy_msg(sp):
    pd = sp.data.get("pd_consent")
    rows = [
        f"Роль: <b>{ROLES.get(sp.role, sp.role)}</b>",
        "Согласие: "
        + (
            f"дано {pd['at'][:16].replace('T', ' ')} (версия {pd['version']})"
            if pd
            else "не дано"
        ),
        "Телефон: "
        + (sp.data.get("phone_mask") or "не передавался")
        + (" · хранится как хеш" if sp.data.get("phone_hash") else ""),
        "Telegram ID: " + ("привязан" if sp.data.get("tg_user") else "—"),
    ]
    return {
        "text": "<b>Ваши данные в боте</b>\n"
        + "\n".join(rows)
        + "\n\nФото и сообщения по заявкам хранятся в карточке заявки. Учебный стенд: в промышленной версии — "
        "журнал согласий, срок хранения и маскирование ПДн в ответах AI.",
        "kb": kb(
            [("🗑 Отозвать согласие и удалить данные", "pd:delete")],
            [("← Меню", "menu")],
        ),
    }


def match_contact(s, sp, phone):
    """Роль по номеру из учёта: водитель / клиент пространства."""
    for role in ("driver", "client"):
        pid = sp.data.get(role)
        person = s.get(Item, pid) if pid else None
        if person and digits(person.data.get("phone")) == digits(phone):
            return role, person.data.get("name", "")
    return None, ""


def on_contact(s, sp, contact, user):
    if str(contact.get("user_id")) != str(user["id"]):
        return [
            {
                "text": "Нужен ваш собственный номер — нажмите кнопку «Поделиться номером».",
                "reply": "contact",
            }
        ]
    if not sp.data.get("pd_consent"):
        return [consent_msg()]
    phone = contact.get("phone_number", "")
    role, name = match_contact(s, sp, phone)
    mask = mask_phone(phone)
    sp.data = {**sp.data, "phone_hash": phone_hash(sp, phone), "phone_mask": mask}
    if role:
        sp.role = role
        sp.data = {**{k: v for k, v in sp.data.items() if k != "tg_wait"}, "tg_role_chosen": True}
        return [
            {
                "text": f"Нашёл вас в учёте: <b>{esc(name)}</b> · {ROLES[role]}.\n"
                f"Номер {mask} сохранён только в виде хеша.",
                "reply": "remove",
            },
            menu(sp),
        ]
    return [
        {
            "text": f"Номер {mask} не найден в учёте парка. В рабочем продукте менеджер добавит вас "
            "по заявке. В демо выберите роль вручную.",
            "reply": "remove",
        },
        role_picker(),
    ]


def on_invite(sp, code):
    role = INVITES.get(code.strip().upper())
    if not role:
        return [
            {
                "text": "Код не подошёл. Проверьте и введите ещё раз или вернитесь назад.",
                "kb": kb([("← Назад", "roles")]),
            }
        ]
    sp.role = role
    sp.data = {
        **{k: v for k, v in sp.data.items() if k != "tg_wait"},
        "tg_role_chosen": True,
    }
    return [
        {"text": f"Код принят: <b>{ROLES[role]}</b>. Права — только этого отдела."},
        menu(sp),
    ]


def menu(sp):
    role = sp.role
    if role in ("manager", "service", "finance", "owner"):
        return {"text": f"<b>{ROLES[role]}</b>\n" + ("Экономика бизнеса и решения — в мобильном дашборде." if role == "owner" else "В демо доступно в веб-кабинете."),
            "kb": kb([("📊 Дашборд" if role == "owner" else "Открыть веб-кабинет", "web")], [("Сменить роль", "roles")])}
    title = f"<b>{ROLES.get(role, role)}</b> · что сделать?"
    rows = {
        "driver": [
            [("💰 Баланс и долг", "d:balance"), ("🚗 Мой автомобиль", "d:car")],
            [("🏖 Выходной завтра", "d:holiday"), ("🛠 Сообщить о проблеме", "d:ticket")],
            [("🚨 Штрафы ГИБДД", "d:fines"), ("📄 Договор PDF", "d:pdf")],
            [("📱 Кабинет водителя", "app:driver")],
        ],
        "client": [
            [("🚘 Подобрать автомобиль", "c:catalog")],
            [("📋 Мои брони", "c:mine"), ("🛠 Обращение", "d:ticket")],
            [("📱 Кабинет клиента", "app:catalog")],
        ],
        "manager": [
            [
                ("📊 Парк сегодня", "m:summary"),
                ("🧾 Брони на подтверждение", "m:drafts"),
            ],
            [("🛠 Открытые заявки", "s:tickets"), ("📱 Кабинет", "app")],
        ],
        "service": [
            [("🛠 Заявки в работе", "s:tickets"), ("📊 Парк сегодня", "m:summary")],
            [("📱 Кабинет", "app")],
        ],
        "finance": [
            [
                ("💳 Сметы на согласование", "f:estimates"),
                ("🏖 Заявления на выходные", "f:holidays"),
            ],
            [("📈 Экономика за 30 дней", "f:economy"), ("📱 Кабинет", "app")],
        ],
    }.get(role, [])
    return {
        "text": title,
        "kb": kb(*rows, [("🔐 Мои данные", "pd:info"), ("🔄 Сменить роль", "roles")]),
    }


def back(sp):
    return kb([("← Меню", "menu"), ("📱 Кабинет", "app")])


def active_contract(s, sp):
    cs = [c for c in visible(s, sp, "contract") if c.data["status"] == "active"]
    return cs[0] if cs else None


def run(s, sp, action, payload, key):
    """Бизнес-команда в точке сохранения: при ошибке откат только её изменений, ответ — текстом."""
    try:
        with s.begin_nested():
            return command(s, sp, action, payload, key), None
    except HTTPException as e:
        return None, str(e.detail)


# ───────────────────────── действия ─────────────────────────


def driver_action(s, sp, act, uid_key):
    c = active_contract(s, sp)
    if act == "balance":
        r = report(s, sp)
        rate = (
            rub(c.data["rate"]) + " в сутки · график " + c.data["schedule"]
            if c
            else "договора нет"
        )
        return [
            {
                "text": "<b>Баланс за 30 дней</b>\n"
                f"Начислено: {rub(r['revenue'])}\nОплачено: {rub(r['payments'])}\n"
                f"Долг: <b>{rub(r['debt'])}</b>\n\nТариф: {rate}",
                "kb": back(sp),
            }
        ]
    if act == "fines":
        # Данные приходят тем же конвейером n8n (источник «Штрафы ГИБДД»), что и в кабинете
        from .integrations import enqueue

        if not c:
            return [{"text": "Нет действующего договора.", "kb": back(sp)}]
        v = get(s, sp, c.data["vehicle"], "vehicle")
        fresh = s.execute(
            sqltext(
                "SELECT status, finished, execution_id FROM source_sync WHERE space=:sp AND source='fines' "
                "AND started > now() - interval '1 hour' ORDER BY started DESC LIMIT 1"
            ),
            {"sp": sp.id},
        ).first()
        if not fresh:
            enqueue(s, sp, "fines")
            return [
                {
                    "text": "🔄 Запросил свежие данные ГИБДД через интеграцию (n8n). Обычно это 2–3 секунды — "
                    "нажмите «Проверить».",
                    "kb": kb([("🔄 Проверить", "d:fines")], [("← Меню", "menu")]),
                }
            ]
        if fresh.status in ("queued", "running"):
            return [
                {
                    "text": "⏳ Конвейер ещё выполняется…",
                    "kb": kb([("🔄 Проверить", "d:fines")], [("← Меню", "menu")]),
                }
            ]
        rec = s.scalar(
            select(Item).where(
                Item.space == sp.id,
                Item.kind == "source_record",
                Item.code == "fines:" + v.code,
            )
        )
        when = (
            fresh.finished.astimezone(MSK).strftime("%H:%M") if fresh.finished else "—"
        )
        src = f"\n\n<i>Источник: ГИБДД (учебный) · n8n #{fresh.execution_id or '—'} · {when} МСК</i>"
        if rec and rec.data["values"].get("fine"):
            val = rec.data["values"]
            return [
                {
                    "text": f"🚨 <b>Постановление {esc(val.get('external_id', ''))}</b>\n"
                    f"Автомобиль {v.code} · {esc(v.data['plate'])}\nСумма: <b>{rub(val['fine'])}</b>\n\n"
                    "По большинству постановлений действует скидка 50% при оплате в течение 20 дней. Если за рулём были не вы — "
                    "сообщите менеджеру." + src,
                    "kb": kb(
                        [("🛠 Оспорить / вопрос менеджеру", "d:ticket")],
                        [("← Меню", "menu")],
                    ),
                }
            ]
        return [
            {
                "text": f"✅ По автомобилю {v.code} новых штрафов нет." + src,
                "kb": back(sp),
            }
        ]
    if act == "car":
        if not c:
            return [
                {
                    "text": "Автомобиль ещё не закреплён — оформите договор.",
                    "kb": back(sp),
                }
            ]
        v = get(s, sp, c.data["vehicle"], "vehicle")
        d = v.data
        return [
            {
                "photo": d.get("image"),
                "text": f"<b>{esc(d['model'])}</b> · {d['year']}\n{v.code} · {esc(d['plate'])}\n"
                f"Пробег {d['mileage']:,} км · следующее ТО на {d['next_to']:,} км\n".replace(
                    ",", " "
                )
                + f"Договор {c.code}: {rub(c.data['rate'])}/сутки, график {c.data['schedule']}",
                "kb": back(sp),
            }
        ]
    if act == "holiday":
        if not c:
            return [{"text": "Нет действующего договора.", "kb": back(sp)}]
        day = str(today() + timedelta(days=1))
        _, err = run(
            s,
            sp,
            "contract.holiday",
            {"id": c.id, "start": day, "end": day, "reason": "Запрос из Telegram"},
            uid_key,
        )
        text = err or (
            f"Заявление на выходной {day[8:]}.{day[5:7]} отправлено в финансовый отдел.\n"
            "После согласования начисление за этот день снимется автоматически."
        )
        return [{"text": text, "kb": back(sp)}]
    if act == "totix":
        last = sp.data.get("tg_last")
        if not last:
            return [
                {
                    "text": "Опишите проблему одним сообщением — можно с фото.",
                    "kb": back(sp),
                }
            ]
        sp.data = {k: v for k, v in sp.data.items() if k != "tg_last"}
        return [ticket_draft_reply(s, sp, last, last, None, [], uid_key)]
    if act == "ticket":
        sp.data = {**sp.data, "tg_wait": "ticket"}
        return [
            {
                "text": "Опишите проблему одним сообщением — можно с фото. Подготовлю обращение; отправку в сервис вы подтвердите кнопкой.",
                "kb": kb([("← Отмена", "menu")]),
            }
        ]
    if act == "pdf":
        if not c:
            return [
                {
                    "text": "Документы появятся после оформления договора.",
                    "kb": back(sp),
                }
            ]
        from .documents import render

        return [
            {
                "document": (render(s, sp, c), f"park-{c.code}.pdf"),
                "text": DISCLAIMER,
            }
        ]
    return [menu(sp)]


def client_action(s, sp, act, arg, uid_key):
    if act in ("dates", "month", "pick", "reserve", "noop"):
        from .tg_calendar import handle as calendar_handle
        try:
            return calendar_handle(s, sp, act, arg, uid_key)
        except HTTPException as exc:
            return [{"text": esc(str(exc.detail)), "kb": back(sp)}]
    if act == "catalog":
        start = today() + timedelta(days=1)
        period = Range(
            datetime.fromisoformat(f"{start}T10:00:00+03:00"),
            datetime.fromisoformat(f"{start + timedelta(days=3)}T10:00:00+03:00"),
            "[)",
        )
        busy = set(
            s.scalars(
                select(Booking.vehicle).where(
                    Booking.space == sp.id,
                    Booking.period.overlaps(period),
                    Booking.state.in_(["active", "confirmed", "hold"]),
                    (Booking.expires == None) | (Booking.expires > now()),  # noqa: E711
                )
            ).all()
        )
        cars = [
            v
            for v in visible(s, sp, "vehicle")
            if v.data["direction"] == "rental"
            and v.data["status"] == "ready"
            and v.id not in busy
        ]
        seen, picks = set(), []
        for v in cars:  # по одной машине каждой модели
            if v.data["model"] not in seen:
                seen.add(v.data["model"])
                picks.append(v)
        out = [{"text": "Свободны на завтра — выберите машину:"}]
        for v in picks[:4]:
            d = v.data
            out.append(
                {
                    "photo": d.get("image"),
                    "text": f"<b>{esc(d['model'])}</b> · {d['class']}\n{rub(d['rate'])} в сутки · {d['year']}",
                    "kb": kb(
                        [
                            (
                                "Выбрать даты аренды",
                                f"c:dates:{v.id}",
                            )
                        ]
                    ),
                }
            )
        out.append(
            {
                "text": "Бронь подтверждает менеджер парка — после проверки документов.",
                "kb": back(sp),
            }
        )
        return out
    if act == "book":
        start = today() + timedelta(days=1)
        r, err = run(
            s,
            sp,
            "contract.create",
            {
                "vehicle": arg,
                "start": str(start),
                "end": str(start + timedelta(days=3)),
            },
            uid_key,
        )
        if err:
            return [{"text": "Не получилось: " + esc(err), "kb": back(sp)}]
        return [
            {
                "text": f"Бронь <b>{r['code']}</b> создана и ждёт подтверждения менеджера.\n"
                "Хотите увидеть другую сторону? «Сменить роль» → сотрудник → менеджер → «Брони на подтверждение».",
                "kb": back(sp),
            }
        ]
    if act == "mine":
        cs = sorted(visible(s, sp, "contract"), key=lambda c: c.created, reverse=True)[
            :5
        ]
        status = {
            "draft": "ждёт подтверждения",
            "confirmed": "подтверждена",
            "active": "действует",
            "completed": "завершена",
            "cancelled": "отменена",
        }
        lines = [
            f"{c.code} · {esc(get(s, sp, c.data['vehicle']).data['model'])} · "
            f"{status.get(c.data['status'], c.data['status'])}"
            for c in cs
        ]
        return [
            {
                "text": "<b>Мои брони</b>\n" + ("\n".join(lines) or "Пока нет"),
                "kb": back(sp),
            }
        ]
    return [menu(sp)]


def staff_action(s, sp, act, arg, uid_key):
    if act == "summary":
        vs = visible(s, sp, "vehicle")
        by = {
            k: sum(1 for v in vs if v.data["status"] == k)
            for k in ("ready", "repair", "inspection")
        }
        busy = len(
            {
                c.data["vehicle"]
                for c in visible(s, sp, "contract")
                if c.data["status"] == "active"
            }
        )
        open_t = [t for t in visible(s, sp, "ticket") if t.data["status"] != "closed"]
        return [
            {
                "text": f"<b>Парк сегодня</b>\nВсего: {len(vs)} · в работе {busy}\n"
                f"Готовы к выдаче: {by['ready']} · ремонт: {by['repair']} · осмотр: {by['inspection']}\n"
                f"Открытых заявок: {len(open_t)}",
                "kb": back(sp),
            }
        ]
    if act == "drafts":
        drafts = [c for c in visible(s, sp, "contract") if c.data["status"] == "draft"][
            -5:
        ]
        if not drafts:
            return [
                {
                    "text": "Новых броней нет. Создайте бронь как клиент — она появится здесь.",
                    "kb": back(sp),
                }
            ]
        return [
            {
                "text": f"<b>{c.code}</b> · {esc(get(s, sp, c.data['vehicle']).data['model'])}\n"
                f"{c.data['start']} → {c.data['end']} · {rub(c.data['rate'])}/сутки",
                "kb": kb([("✅ Подтвердить", f"m:confirm:{c.id}")]),
            }
            for c in drafts
        ] + [
            {
                "text": "Подтверждение проверяет документы клиента и пересечение броней.",
                "kb": back(sp),
            }
        ]
    if act == "confirm":
        r, err = run(s, sp, "contract.confirm", {"id": arg}, uid_key)
        return [
            {
                "text": err
                or f"Бронь {r['code']} подтверждена — клиент увидит это в боте.",
                "kb": back(sp),
            }
        ]
    if act == "tickets":
        ts = [
            t for t in visible(s, sp, "ticket") if t.data["status"] not in ("closed",)
        ][:6]
        nxt = {
            "new": ("Составить смету", "s:est"),
            "approved": ("Взять в работу", "s:start"),
            "repair": ("Ремонт завершён", "s:done"),
        }
        status = {
            "new": "новая",
            "estimate": "смета у финансов",
            "approved": "смета согласована",
            "repair": "в ремонте",
            "quality": "контроль качества",
        }
        out = []
        for t in ts:
            d = t.data
            v = get(s, sp, d["vehicle"])
            step = nxt.get(d["status"]) if sp.role == "service" else None
            out.append(
                {
                    "text": f"<b>{t.code}</b> · {esc(d['title'])}\n{esc(v.data['model'])} · {status.get(d['status'], d['status'])}"
                    + (
                        f" · {rub(d['estimate'])}"
                        if float(d.get("estimate") or 0)
                        else ""
                    ),
                    "kb": kb([(step[0], f"{step[1]}:{t.id}")]) if step else None,
                }
            )
        out.append(
            {
                "text": "Ведёт ремонт роль «Сервис», смету согласуют «Финансы».",
                "kb": back(sp),
            }
        )
        return out
    if act in ("est", "start", "done"):
        t = get(s, sp, arg, "ticket")
        action, payload = {
            "est": (
                "ticket.estimate",
                {
                    "id": arg,
                    "amount": float(t.data.get("estimate") or 0) or 9500,
                    "payer": "company",
                },
            ),
            "start": ("ticket.start", {"id": arg}),
            "done": ("ticket.complete", {"id": arg}),
        }[act]
        r, err = run(s, sp, action, payload, uid_key)
        msg = {
            "est": "Смета отправлена финансам на согласование.",
            "start": "Машина принята в ремонт, начисления по ней встали.",
            "done": "Ремонт завершён, расход проведён в экономику машины.",
        }[act]
        return [{"text": err or f"{t.code}: {msg}", "kb": back(sp)}]
    return [menu(sp)]


def finance_action(s, sp, act, arg, uid_key):
    if act == "estimates":
        ts = [t for t in visible(s, sp, "ticket") if t.data["status"] == "estimate"][:5]
        if not ts:
            return [
                {
                    "text": "Смет на согласовании нет. Сервис отправит — появятся здесь.",
                    "kb": back(sp),
                }
            ]
        return [
            {
                "text": f"<b>{t.code}</b> · {esc(t.data['title'])}\n{esc(get(s, sp, t.data['vehicle']).data['model'])} · "
                f"смета {rub(t.data['estimate'])}",
                "kb": kb([("✅ Согласовать", f"f:approve:{t.id}")]),
            }
            for t in ts
        ] + [{"text": "Согласованная смета уходит обратно в сервис.", "kb": back(sp)}]
    if act == "approve":
        r, err = run(s, sp, "ticket.approve", {"id": arg}, uid_key)
        return [{"text": err or f"Смета {r['code']} согласована.", "kb": back(sp)}]
    if act == "holidays":
        cs = [c for c in visible(s, sp, "contract") if c.data.get("holiday_request")][
            :5
        ]
        if not cs:
            return [
                {
                    "text": "Заявлений нет. Попросите выходной как водитель — оно придёт сюда.",
                    "kb": back(sp),
                }
            ]
        return [
            {
                "text": f"<b>{c.code}</b> · выходной {', '.join(c.data['holiday_request'])}",
                "kb": kb([("✅ Согласовать", f"f:hday:{c.id}")]),
            }
            for c in cs
        ] + [
            {
                "text": "После согласования начисление за день снимается сторно.",
                "kb": back(sp),
            }
        ]
    if act == "hday":
        r, err = run(s, sp, "contract.approve_holiday", {"id": arg}, uid_key)
        return [
            {
                "text": err or f"Выходной по договору {r['code']} согласован.",
                "kb": back(sp),
            }
        ]
    if act == "economy":
        r = report(s, sp)
        top = sorted(r["rows"], key=lambda x: float(x["result"]))[:3]
        worst = "\n".join(
            f"· {esc(x['model'])} {x['code']}: {rub(x['result'])}" for x in top
        )
        return [
            {
                "text": f"<b>Экономика за 30 дней</b>\nВыручка: {rub(r['revenue'])}\nРасходы: {rub(r['expenses'])}\n"
                f"Общие расходы: {rub(r['overhead'])}\nРезультат: <b>{rub(r['profit'])}</b>\n\n"
                f"Слабые машины:\n{worst}",
                "kb": back(sp),
            }
        ]
    return [menu(sp)]


# ───────────────────────── входная точка воркера ─────────────────────────


def _space(s, telegram_id, chat_id):
    s.execute(sqltext("SELECT pg_advisory_xact_lock(hashtext(:id))"), {"id": "telegram:" + telegram_id})
    sp = s.scalar(
        select(Space)
        .where(Space.data["tg_user"].astext == telegram_id)
        .with_for_update()
    )
    created = False
    if not sp:
        sp = claim_space(s)
        sp.role = "driver"
        sp.data = {**sp.data, "tg_user": telegram_id, "tg_chat": str(chat_id)}
        created = True
    sp.touched = now()
    sp.data = {**sp.data, "tg_chat": str(chat_id)}
    return sp, created


def _save_photo(s, sp, raw, update_id):
    fid = hashlib.sha256(f"{sp.id}:{update_id}".encode()).hexdigest()[:32]
    if not s.get(Item, fid):
        s.add(
            Item(
                id=fid,
                space=sp.id,
                kind="file",
                code=f"TG-{update_id}",
                version=1,
                data={
                    "name": "telegram-photo.jpg",
                    "ext": ".jpg",
                    "size": len(raw),
                    "creator_role": sp.role,
                },
            )
        )
        folder = FILES / sp.id
        folder.mkdir(exist_ok=True, parents=True)
        (folder / f"{fid}.jpg").write_bytes(raw)
    return fid


HELP = re.compile(
    r"что (ты )?(умеешь|можешь)|^помо(щь|ги)|^help\b|^меню$|^привет|^здравствуй", re.I
)

def help_text(sp):
    common = "Пишите своими словами: найду ответ в правилах или ваших данных. Для проблемы подготовлю заявку — создание подтвердите кнопкой."
    by_role = {
        "driver": "Как водитель вы можете: посмотреть баланс и долг, свою машину, попросить выходной, сообщить о проблеме (можно с фото), скачать договор.",
        "client": "Как клиент проката вы можете: подобрать свободную машину и забронировать её, посмотреть свои брони, задать вопрос или сообщить о проблеме.",
    }
    return {
        "text": by_role.get(sp.role, "У сотрудников — свои кнопки в меню роли.")
        + "\n\n"
        + common,
        "kb": menu(sp)["kb"],
    }


def ticket_draft_reply(s, sp, text, title, priority, photos, key):
    c = active_contract(s, sp)
    vehicle = c.data["vehicle"] if c else None
    if not vehicle:
        owned = visible(s, sp, "vehicle")
        vehicle = owned[0].id if owned and sp.role == "driver" else None
    if not vehicle:
        return {
            "text": "Сначала оформите аренду — обращение привязывается к машине.",
            "kb": back(sp),
        }
    if priority not in ("urgent", "technical", "normal"):
        priority = (
            "urgent"
            if any(w in text.lower() for w in ("дтп", "авари", "не завод"))
            else "technical"
        )
    payload = {
            "vehicle": vehicle,
            "title": title[:150],
            "description": text,
            "priority": priority,
            "photos": photos,
    }
    code = "DRAFT-" + hashlib.sha256(key.encode()).hexdigest()[:24]
    draft = s.scalar(select(Item).where(Item.space == sp.id, Item.kind == "agent_draft", Item.code == code))
    if not draft:
        from .seed import add
        draft = add(s, sp.id, "agent_draft", code, {
            "role": sp.role, "action": "ticket.create", "payload": payload,
            "status": "pending", "expires": (now() + timedelta(minutes=10)).isoformat(),
            "vehicle_code": get(s, sp, vehicle, "vehicle").code,
        })
    return {
        "text": f"Подготовлен черновик обращения «{esc(title[:80])}»{' с фото' if photos else ''}.\n"
        f"Автомобиль: {esc(draft.data['vehicle_code'])}. В сервис пока не отправлено.",
        "kb": kb([("Подтвердить отправку в сервис", "agentconfirm:" + draft.id)], [("← Отмена", "menu")]),
    }


def agent_message(space_id, role, message, key):
    from .agent import run as run_agent

    jid = hashlib.sha256((space_id + ":" + role + ":agent:" + key).encode()).hexdigest()[:32]
    with db() as s:
        s.execute(
            sqltext("SELECT pg_advisory_xact_lock(hashtext(:id))"), {"id": space_id}
        )
        old = s.get(Job, jid)
        if old:
            return (
                old.result
                if old.state == "done"
                else {
                    "answer": "Запрос уже обрабатывался. Откройте кабинет или повторите вопрос позже.",
                    "drafts": [],
                    "sources": [],
                }
            )
        count = s.scalar(
            select(func.count())
            .select_from(Job)
            .where(
                Job.space == space_id,
                Job.kind == "ai",
                Job.due > now() - timedelta(hours=1),
            )
        )
        if count >= 10:
            return {
                "answer": "Лимит 10 AI-запросов в час исчерпан. Кнопки кабинета доступны.",
                "drafts": [],
                "sources": [],
            }
        j = Job(
            id=jid,
            space=space_id,
            kind="ai",
            state="running",
            attempts=1,
            lease=now() + timedelta(minutes=6),
            data={"mode": "agent", "prompt": message[:2000], "role": role},
            result={},
        )
        s.add(j)
    try:
        result = run_agent(j)
        with db() as s:
            row = s.get(Job, jid)
            if row:
                row.state = "done"
                row.result = result
        return result
    except Exception:
        result = {
            "answer": "AI временно недоступен. Воспользуйтесь кнопками кабинета; автоматическая заявка не создавалась.",
            "drafts": [],
            "sources": [],
        }
        with db() as s:
            row = s.get(Job, jid)
            if row:
                row.state = "failed"
                row.result = {"error": result["answer"]}
        return result


def freeze_reply(messages):
    saved = []
    for message in messages:
        row = dict(message)
        if row.get("kb"):
            row["kb"] = row["kb"].model_dump(mode="json", exclude_none=True)
        if row.get("document"):
            raw, name = row["document"]
            row["document"] = {"name": name, "base64": base64.b64encode(raw).decode()}
        saved.append(row)
    return saved


def thaw_reply(messages):
    restored = []
    for message in messages:
        row = dict(message)
        if row.get("kb"):
            row["kb"] = InlineKeyboardMarkup.model_validate(row["kb"])
        if row.get("document"):
            doc = row["document"]
            row["document"] = (base64.b64decode(doc["base64"]), doc["name"])
        restored.append(row)
    return restored


def handle(data, space_id=None):
    """Логика бота без транспорта → (chat_id, сообщения, callback_id).

    space_id задан — апдейт пришёл из веб-эмулятора: отвечаем от имени текущей
    демосессии, ничего не отправляя в Telegram."""
    cb = data.get("callback_query")
    m = data.get("message") or (cb or {}).get("message") or {}
    user = (cb or m).get("from", {})
    chat = m.get("chat", {})
    if not user or chat.get("type") != "private":
        return None
    key = "tg:" + str(data["update_id"])
    raw = (
        asyncio.run(photo_bytes(m["photo"][-1]["file_id"]))
        if (not cb and m.get("photo") and not space_id)
        else None
    )
    triage = None
    ctx = None
    text_in = (m.get("text") or "").strip() if not cb else ""
    if text_in and not text_in.startswith("/") and not HELP.search(text_in) and not raw:
        # LLM вызываем до основной транзакции: она держит блокировку пространства,
        # а учёт расхода AI пишется отдельным соединением
        with db() as s:
            sp0 = (
                s.get(Space, space_id)
                if space_id
                else s.scalar(
                    select(Space).where(Space.data["tg_user"].astext == str(user["id"]))
                )
            )
            ctx = (
                (
                    sp0.id,
                    sp0.role,
                    sp0.data.get("tg_wait"),
                    bool(sp0.data.get("pd_consent")),
                    bool(sp0.data.get("tg_role_chosen")),
                )
                if sp0
                else None
            )
        # без согласия на ПДн текст в модель не отправляем
        if ctx and ctx[1] in ROLES and ctx[2] != "invite" and ctx[3] and ctx[4]:
            triage = agent_message(ctx[0], ctx[1], text_in, key)
    with db() as s:
        if space_id:
            sp = s.scalar(select(Space).where(Space.id == space_id).with_for_update())
            created = False
            sp.touched = now()
        else:
            sp, created = _space(s, str(user["id"]), chat["id"])
        reply_key = "botreply:" + str(data["update_id"])
        cached = s.scalar(select(Receipt).where(Receipt.space == sp.id, Receipt.key == reply_key))
        if cached:
            same_context = (
                cached.result["role"] == sp.role
                and cached.result.get("consent") == bool(sp.data.get("pd_consent"))
                and cached.result.get("chosen") == bool(sp.data.get("tg_role_chosen"))
            )
            restored = thaw_reply(cached.result["messages"]) if same_context else (
                [consent_msg()] if not sp.data.get("pd_consent") else
                [role_picker()] if not sp.data.get("tg_role_chosen") else [menu(sp)]
            )
            return chat["id"], restored, (cb.get("id") if cb else None), sp.role
        received = s.scalar(
            select(Event.id).where(
                Event.space == sp.id, Event.data["webhook_key"].astext == key
            )
        )
        if not received:
            s.add(
                Event(
                    space=sp.id,
                    title=(
                        "Эмулятор бота: сообщение обработано"
                        if space_id
                        else "Telegram: входящий вебхук обработан"
                    ),
                    role=sp.role,
                    data={
                        "channel": "telegram",
                        "webhook_key": key,
                        **({"sim": True} if space_id else {}),
                    },
                )
            )
        # Navigation cancels an unfinished text form. /start and /menu must not
        # leave an invisible "next message is a ticket" state behind.
        if cb or text_in.startswith("/"):
            sp.data = {k: v for k, v in sp.data.items() if k != "tg_wait"}
        if triage and (not ctx or sp.role != ctx[1]):
            triage = None
        if cb:
            action = cb.get("data", "")
            head, _, rest = action.partition(":")
            act, _, arg = rest.partition(":")
            if action == "roles":
                out = [role_picker()]
            elif action == "pd:yes":
                sp.data = {
                    **sp.data,
                    "pd_consent": {"at": now().isoformat(), "version": PD_VERSION},
                }
                s.add(
                    Event(
                        space=sp.id,
                        title="Бот: получено согласие на обработку ПДн",
                        role=sp.role,
                        data={"channel": "telegram", "consent": PD_VERSION},
                    )
                )
                out = (
                    [{"text": "Согласие сохранено. Продолжим."}, menu(sp)]
                    if sp.data.get("tg_role_chosen")
                    else identify_msgs()
                )
            elif action == "pd:no":
                out = [
                    {
                        "text": "Понимаю. Без согласия бот не обрабатывает персональные данные: можно посмотреть "
                        "демо без личных данных или вернуться позже.",
                        "kb": kb(
                            [("✅ Передумал — согласен", "pd:yes")],
                            [("🎭 Демо без личных данных", "roles")],
                        ),
                    }
                ]
            elif action == "pd:info":
                out = [privacy_msg(sp)]
            elif action == "pd:delete":
                out = [
                    {
                        "text": "Удалить согласие, номер и привязку Telegram? Действие необратимо.",
                        "kb": kb(
                            [("🗑 Да, удалить", "pd:delete_yes")], [("← Отмена", "menu")]
                        ),
                    }
                ]
            elif action == "pd:delete_yes":
                drop = (
                    "pd_consent",
                    "phone_hash",
                    "phone_mask",
                    "tg_wait",
                    "tg_role_chosen",
                    "tg_last",
                )
                if space_id:
                    # эмулятор: веб-сессию не трогаем, стираем только данные бота
                    sp.data = {k: v for k, v in sp.data.items() if k not in drop}
                    s.add(
                        Event(
                            space=sp.id,
                            title="Бот: согласие отозвано, данные бота удалены",
                            role=sp.role,
                            data={"channel": "telegram"},
                        )
                    )
                else:
                    # Telegram: личное пространство пользователя удаляется целиком
                    # (заявки, фото, договоры, привязка); файлы чистит воркер
                    s.add(Job(kind="cleanup_files", data={"space": sp.id}, result={}))
                    s.delete(sp)
                out = [
                    {
                        "text": "Данные удалены, согласие отозвано. Чтобы начать заново — /start."
                    }
                ]
            elif action == "id:staff":
                sp.data = {**sp.data, "tg_wait": "invite"}
                out = [
                    {
                        "text": "Введите код приглашения от руководителя.\n\n<i>Демо-коды: MANAGER-2026, "
                        "SERVICE-2026, FINANCE-2026</i>",
                        "kb": kb([("← Назад", "roles")]),
                    }
                ]
            elif action == "staff":
                out = [staff_picker()]
            elif head == "role" and act in ROLES:
                sp.role = act
                sp.data = {
                    **{k: v for k, v in sp.data.items() if k != "tg_wait"},
                    "tg_role_chosen": True,
                }
                out = [
                    {
                        "text": f"Вы вошли как <b>{ROLES[act]}</b>. Данные и права — только этой роли.",
                        "reply": "remove",
                    },
                    menu(sp),
                ]
            elif head in ("agentconfirm", "d", "c", "m", "s", "f") and not sp.data.get(
                "pd_consent"
            ):
                # личные данные роли (баланс, договор, заявки) — только после согласия на ПДн
                out = [consent_msg()]
            elif head in ("agentconfirm", "d", "c", "m", "s", "f") and not sp.data.get("tg_role_chosen"):
                out = [role_picker("Сначала выберите роль.\n\n")]
            elif head == "agentconfirm":
                from .agent import confirm

                try:
                    r = confirm(s, sp, rest, via="telegram")
                    out = [
                        {
                            "text": "Заявка <b>" + esc(r["code"]) + "</b> создана.",
                            "kb": back(sp),
                        }
                    ]
                except HTTPException as e:
                    out = [{"text": esc(str(e.detail)), "kb": back(sp)}]
            elif head == "d":
                out = driver_action(s, sp, act, key)
            elif head == "c":
                out = client_action(s, sp, act, arg, key)
            elif head in ("m", "s"):
                out = staff_action(s, sp, act, arg, key)
            elif head == "f":
                out = finance_action(s, sp, act, arg, key)
            else:
                out = [menu(sp)]
        else:
            text = (m.get("text") or m.get("caption") or "").strip()
            consent = bool(sp.data.get("pd_consent"))
            if m.get("contact"):
                out = on_contact(s, sp, m["contact"], user)
            elif (
                sp.data.get("tg_wait") == "invite" and text and not text.startswith("/")
            ):
                out = on_invite(sp, text)
            elif created or text.startswith("/start"):
                out = ([menu(sp)] if sp.data.get("tg_role_chosen") else identify_msgs()) if consent else [consent_msg()]
            elif text in ("/role", "/roles"):
                out = [role_picker()]
            elif text == "/privacy":
                out = [privacy_msg(sp)]
            elif text == "/delete_me":
                out = [
                    {
                        "text": "Удалить согласие, номер и привязку Telegram? Действие необратимо.",
                        "kb": kb(
                            [("🗑 Да, удалить", "pd:delete_yes")], [("← Отмена", "menu")]
                        ),
                    }
                ]
            elif not consent and ((text and not text.startswith("/")) or raw):
                # свободный текст и фото — только после согласия на обработку ПДн
                out = [consent_msg()]
            elif not sp.data.get("tg_role_chosen"):
                out = identify_msgs() if consent else [consent_msg()]
            elif text in ("/menu", "/help"):
                out = [menu(sp)]
            elif text in ("/balance",) and sp.role == "driver":
                out = driver_action(s, sp, "balance", key)
            elif text in ("/car",) and sp.role == "driver":
                out = driver_action(s, sp, "car", key)
            elif HELP.search(text):
                out = [help_text(sp)]
            elif triage and not raw:
                sp.data = {k: v for k, v in sp.data.items() if k != "tg_wait"}
                buttons = [
                    (
                        "Подтвердить: " + d["payload"]["title"][:35],
                        "agentconfirm:" + d["id"],
                    )
                    for d in triage.get("drafts", [])
                ]
                citations = "; ".join(
                    dict.fromkeys(x["title"] for x in triage.get("sources", []))
                )
                msg = re.sub(
                    r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", esc(triage["answer"][:3200])
                ) + (
                    "\n\n<i>Источники: " + esc(citations[:500]) + "</i>"
                    if citations
                    else ""
                )
                out = [
                    {
                        "text": msg,
                        "kb": kb(
                            *[[(label, callback)] for label, callback in buttons],
                            [("← Меню", "menu")],
                        ),
                    }
                ]
            elif sp.role in ("driver", "client") and raw:
                sp.data = {k: v for k, v in sp.data.items() if k != "tg_wait"}
                photos = [_save_photo(s, sp, raw, data["update_id"])]
                out = [ticket_draft_reply(s, sp, text, text or "Фото из Telegram", None, photos, key)]
            elif text and not text.startswith("/"):
                out = [{"text": "Не удалось получить ответ помощника. Повторите вопрос или откройте кабинет. Заявка не создавалась.", "kb": back(sp)}]
            else:
                out = [menu(sp)]
        chat_id = chat["id"]
        role = sp.role
        for i, message in enumerate(out):
            message["id"] = str(data["update_id"]) + ":" + str(i)
        if cb and m.get("message_id") and out and not any(out[0].get(k) for k in ("photo", "document", "reply")):
            out[0]["edit_target"] = str(m["message_id"])
            out[0]["id"] = str(m["message_id"])
        if sp not in s.deleted:
            s.add(Receipt(space=sp.id, key=reply_key, result={"messages": freeze_reply(out), "role": role,
                "consent": bool(sp.data.get("pd_consent")), "chosen": bool(sp.data.get("tg_role_chosen"))}))
    return chat_id, out, (cb.get("id") if cb else None), role


def process(data):
    """Апдейт из настоящего Telegram: логика + доставка через Bot API."""
    r = handle(data)
    if not r:
        return {"ignored": True}
    chat_id, out, callback_id, _ = r
    delivered = asyncio.run(_deliver(chat_id, out, callback_id))
    return {"sent": len(out), "message_ids": delivered}


def _as_json(m):
    """Сообщение бота → JSON для веб-эмулятора (тот же текст и те же кнопки)."""
    rows = []
    markup = m.get("kb")
    for row in (markup.inline_keyboard if markup else []):
        rows.append(
            [
                {
                    "text": b.text,
                    "data": b.callback_data,
                    "url": b.url,
                    "app": bool(b.web_app),
                    "app_url": b.web_app.url if b.web_app else None,
                }
                for b in row
            ]
        )
    out = {"text": m.get("text", ""), "kb": rows, "id": m.get("id"), "edit_target": m.get("edit_target")}
    if m.get("reply"):
        out["reply"] = m["reply"]
    # фото — только если файл реально есть в статике (в старых пространствах путь мог устареть)
    if m.get("photo") and any(
        (base / m["photo"].lstrip("/")).is_file()
        for base in (ROOT / "dist", ROOT / "public")
    ):
        out["photo"] = m["photo"]
    if m.get("document"):
        raw, name = m["document"]
        out["document"] = {"name": name, "size": len(raw)}
        if len(raw) < 600_000:
            out["document"]["data"] = (
                "data:application/pdf;base64," + base64.b64encode(raw).decode()
            )
    return out


def simulate(data):
    """Апдейт из веб-эмулятора: та же логика, ответ возвращается JSON-ом."""
    r = handle(data["update"], space_id=data["space"])
    if not r:
        return {"messages": []}
    _, out, _, role = r
    return {"messages": [_as_json(m) for m in out], "role": role}
