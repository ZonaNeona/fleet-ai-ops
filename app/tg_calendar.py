"""Inline booking calendar, sharing prices and reservations with the Mini App."""

import calendar
from datetime import date, timedelta

from sqlalchemy.exc import IntegrityError

from .domain import command, fail, get, own, today
from .miniapp import rental_quote


def render(s, sp):
    from .telegram import esc, kb, rub

    state = sp.data.get("tg_booking", {})
    if not state.get("vehicle"):
        fail("Сначала выберите автомобиль")
    v = get(s, sp, state["vehicle"], "vehicle")
    own(s, sp, v)
    month = date.fromisoformat(state.get("month", str(today().replace(day=1))))
    names = [
        "Январь",
        "Февраль",
        "Март",
        "Апрель",
        "Май",
        "Июнь",
        "Июль",
        "Август",
        "Сентябрь",
        "Октябрь",
        "Ноябрь",
        "Декабрь",
    ]
    rows = [
        [("‹", "c:month:-1"), (f"{names[month.month - 1]} {month.year}", "c:noop"), ("›", "c:month:1")],
        [(d, "c:noop") for d in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]],
    ]
    for week in calendar.monthcalendar(month.year, month.month):
        row = []
        for n in week:
            day = date(month.year, month.month, n) if n else None
            valid = day and day >= today()
            chosen = day and str(day) in (state.get("start"), state.get("end"))
            row.append(
                (("·" if not valid else ("✓" if chosen else "") + str(n)), "c:pick:" + str(day) if valid else "c:noop")
            )
        rows.append(row)
    text = f"<b>{esc(v.data['model'])}</b>\nВыберите дату {'возврата' if state.get('start') and not state.get('end') else 'получения'}. Время — 10:00 МСК."
    if state.get("start"):
        text += "\nПолучение: " + state["start"]
    if state.get("end"):
        quote = rental_quote(s, sp, state)
        state = {**state, "quote_version": quote["version"]}
        sp.data = {**sp.data, "tg_booking": state}
        text += f"\nВозврат: {state['end']}\nАренда: <b>{rub(quote['total'])}</b> · {quote['days']} сут.\nЗалог отдельно: {rub(quote['deposit'])}. Резерв — 30 минут."
        rows.append([("Забронировать за " + rub(quote["total"]), "c:reserve")])
    rows.append([("Открыть Mini App", "app:catalog"), ("← Меню", "menu")])
    return [{"text": text, "kb": kb(*rows)}]


def handle(s, sp, act, arg, key):
    from .telegram import esc, kb

    if sp.role != "client":
        fail("Выберите роль клиента", 403)
    state = dict(sp.data.get("tg_booking", {}))
    if act == "dates":
        v = get(s, sp, arg, "vehicle")
        own(s, sp, v)
        if v.data["direction"] not in ("rental", "commercial"):
            fail("Выберите автомобиль проката")
        state = {"vehicle": v.id, "month": str(today().replace(day=1))}
    elif act == "month":
        month = date.fromisoformat(state.get("month", str(today().replace(day=1))))
        if arg not in ("-1", "1"):
            fail("Некорректный месяц")
        ordinal = month.year * 12 + month.month - 1 + int(arg)
        month = date(ordinal // 12, ordinal % 12 + 1, 1)
        if month < today().replace(day=1) or month > today() + timedelta(days=365):
            return render(s, sp)
        state["month"] = str(month)
    elif act == "pick":
        try:
            picked = date.fromisoformat(arg)
        except ValueError:
            fail("Некорректная дата")
        if picked < today() or picked > today() + timedelta(days=730):
            fail("Дата вне диапазона")
        if not state.get("start") or state.get("end") or str(picked) <= state["start"]:
            state["start"] = str(picked)
            state.pop("end", None)
        else:
            state["end"] = str(picked)
    elif act == "reserve":
        if not state.get("end") or not state.get("quote_version"):
            fail("Сначала выберите даты")
        try:
            with s.begin_nested():
                c = command(
                    s, sp, "contract.create", {k: state[k] for k in ("vehicle", "start", "end", "quote_version")}, key
                )
        except IntegrityError:
            fail("Автомобиль уже занят на эти даты. Выберите другой период.", 409)
        return [
            {
                "text": f"Бронь <b>{esc(c['code'])}</b> создана. Менеджер подтвердит её после проверки документов. Резерв действует 30 минут.",
                "kb": kb([("Моя аренда", "app:rentals/" + c["id"])], [("← Меню", "menu")]),
            }
        ]
    sp.data = {**sp.data, "tg_booking": state}
    return render(s, sp)
