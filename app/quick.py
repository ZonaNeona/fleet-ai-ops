"""Instant answers to the owner's most frequent questions, built from the agent's own tools.

No model: the intent is matched by narrow keywords, the tools run for real under the job's role (their timing and
output go into the trace) and the answer is assembled from what they returned — the numbers always match the
screens. A vague, «why» or advice question goes to the agent; so does one that touches two topics at once.
"""

import re
import time
from collections.abc import Callable
from decimal import Decimal

from fastapi import HTTPException

from .agent import execute

Handler = Callable[[str, str, list], str]


def rub(v) -> str:
    return f"{Decimal(v):,.0f}".replace(",", " ") + " ₽"


def call(space, role, trace, name, args=None):
    started = time.monotonic()
    result = execute(space, role, name, args or {}, "quick:" + name)
    trace.append({"step": "tool", "title": name, "ms": round((time.monotonic() - started) * 1000), "status": "success",
                  "arguments": args or {}, "output": result, "role": role})
    return result


def worst(space, role, trace):
    r = call(space, role, trace, "vehicle_economics", {"worst": 3})
    lines = [f"**Хуже всех по результату за {r['period'][0]} — {r['period'][1]}:**"]
    for v in r["vehicles"]:
        lines.append(f"• **{v['code']}** {v['model']} — результат {rub(v['result'])}: выручка {rub(v['revenue'])}, "
                     f"расходы {rub(v['expenses'])}, доля накладных {rub(v['overhead'])}")
    lines.append("\nРазбивка по каждой машине — в разделе «Аналитика».")
    return "\n".join(lines)


def debt(space, role, trace):
    r = call(space, role, trace, "get_balance")
    aging = r.get("aging") or {}
    parts = ", ".join(f"{k} дн. — {rub(v)}" for k, v in aging.items() if Decimal(str(v or 0)))
    own = role in ("driver", "client")
    return (f"**{'Ваш долг' if own else 'Долг водителей и клиентов'}: {rub(r['debt'])}.** За период начислено "
            f"{rub(r['revenue'])}, поступило {rub(r['payments'])}." + (f"\nПо возрасту: {parts}." if parts else "") +
            ("" if own else "\n\nКому звонить первым — в блоке «Сделать сейчас» на главной."))


def repair(space, role, trace):
    r = call(space, role, trace, "list_vehicles", {"status": "repair"})
    if not r["count"]:
        return "Сейчас ни одна машина не стоит в ремонте."
    lines = [f"**В ремонте: {r['count']}**"]
    for v in r["vehicles"][:8]:
        days = f", {v['days_in_repair']} дн." if v.get("days_in_repair") is not None else ""
        lines.append(f"• **{v['code']}** {v['model']}{days}")
    return "\n".join(lines)


def hiring(space, role, trace):
    p = call(space, role, trace, "crm_pipeline", {"funnel": "hiring"})
    sm = p["summary"]
    stuck = [d for f in p["funnels"] for d in f["stuck"]]
    lines = [f"**Найм водителей:** {sm['hiring_won']} из {sm['hiring_total']} вышли на линию ({sm['hiring_conversion']}%)."]
    if stuck:
        lines.append(f"Зависли дольше нормы: **{len(stuck)}**")
        lines += [f"• {d['title']} — {d['days_in_stage']} дн. на стадии «{d['stage']}», {d['manager']}" for d in stuck[:5]]
    else:
        lines.append("Зависших кандидатов нет.")
    return "\n".join(lines)


def crm_gap(space, role, trace):
    p = call(space, role, trace, "crm_pipeline", {})
    gaps = p["payment_mismatches"]
    if not gaps:
        return "Оплаты в Битрикс24 и в учёте сходятся."
    lines = [f"**Расхождений «оплачено в CRM ↔ учёт»: {len(gaps)}**"]
    lines += [f"• {r['title']} ({r['contract']}) — {r['note']}" for r in gaps[:5]]
    return "\n".join(lines)


def now_list(space, role, trace):
    rows = call(space, role, trace, "get_signals")["signals"]  # fleet-wide: the tool is not open to a driver or client
    if not rows:
        return "Срочного нет: долги, аренды, заявки сервиса и найм в норме."
    lines = [f"**Сделать сейчас: {len(rows)}**"]
    lines += [f"• **{r['label']}** — {r['title']}: {r['reason']}. {r['action']}" for r in rows[:6]]
    return "\n".join(lines)


INTENTS: list[tuple[re.Pattern[str], Callable]] = [
    (re.compile(r"худш\w* (машин|авто)|убыточн|в минусе|низк\w* результат|какие .*машин.* (хуже|минус)"), worst),
    (re.compile(r"долг|задолженн|должник|сколько (нам )?должны"), debt),
    (re.compile(r"(в|на) ремонте|простаива|простой|стоят в сервисе"), repair),
    (re.compile(r"найм|кандидат|воронк\w* найма|завис\w* .*(отклик|водител)"), hiring),
    (re.compile(r"сверк|оплачено в (crm|битрикс)|расхожден"), crm_gap),
    (re.compile(r"что (сделать|делать) (сейчас|сегодня)|сделать сейчас|на что обратить|что горит|срочн"), now_list),
]
# «Why», advice and conditional questions need reasoning: the agent answers them.
SPECIFIC = re.compile(r"почему|зачем|посовет|что делать с|как (исправ|улучш|поднять|снизить)|если |спрогноз|сравни .* с ")


def match(question: str):
    q = question.lower().replace("ё", "е")
    if SPECIFIC.search(q) and "что делать сейчас" not in q:
        return None
    found = {h for p, h in INTENTS if p.search(q)}
    return found.pop() if len(found) == 1 else None


def answer(space, role, question, trace):
    """The quick answer or None; a tool the role may not use sends the question to the agent instead."""
    handler = match(question)
    if not handler:
        return None
    try:
        return handler(space, role, trace)
    except HTTPException:
        return None
