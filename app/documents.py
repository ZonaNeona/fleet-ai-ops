import html
import io

from .domain import calendar, get, serialize
from .reports import entries, ledger_row


def render(s, sp, x, format="pdf"):
    d = serialize(x)
    rows = []
    for key, kind in [("vehicle", "vehicle"), ("client", "client"), ("investor", "investor")]:
        if d.get(key):
            obj = get(s, sp, d[key], kind)
            d[key] = (obj.data.get("model") or obj.data.get("name") or obj.code) + " · " + obj.code
    if x.kind == "contract":
        rows = calendar(x)
    elif x.kind == "statement":
        rows = x.data["lines"]
    else:
        rows = [
            ledger_row(e)
            for e in entries(s, sp, vehicle=x.id if x.kind == "vehicle" else x.data.get("vehicle"), limit=300)
        ]
    titles = {
        "date": "Дата",
        "amount": "Сумма, ₽",
        "reason": "Основание",
        "model": "Автомобиль",
        "income": "Поступления, ₽",
        "expenses": "Расходы, ₽",
        "vehicle": "Код автомобиля",
        "kind": "Тип операции",
    }
    rows = [{titles.get(k, k): v for k, v in row.items() if k in titles and k != "vehicle"} for row in rows]
    if x.kind == "contract" and x.data.get("returned_at"):
        d.update(
            returned_at=x.data["returned_at"],
            return_mileage=x.data["return_mileage"],
            excess_km=x.data.get("excess_km", 0),
        )
    if format == "xlsx":
        from openpyxl import Workbook

        w = Workbook()
        ws = w.active
        ws.title = "Расчёт"
        ws.append(["Учебный таксопарк · учебный документ", x.code])
        if rows:
            keys = list(rows[0])
            ws.append(keys)
            for r in rows:
                vals = []
                for k in keys:
                    v = str(r.get(k, ""))
                    vals.append("'" + v if v.startswith(("=", "+", "-", "@")) else v)
                ws.append(vals)
        out = io.BytesIO()
        w.save(out)
        return out.getvalue()
    if format != "pdf":
        raise ValueError("Неподдерживаемый формат")
    from weasyprint import HTML

    labels = {
        "vehicle": "Автомобиль",
        "client": "Клиент",
        "investor": "Владелец",
        "status": "Статус",
        "start": "Начало",
        "end": "Окончание",
        "rate": "Ставка, ₽",
        "schedule": "График",
        "deposit": "Залог, ₽",
        "final_payment": "Выкупной платёж, ₽",
        "month": "Месяц",
        "amount": "Сумма, ₽",
        "basis": "Основание",
        "title": "Обращение",
        "returned_at": "Дата возврата",
        "return_mileage": "Пробег при возврате",
        "excess_km": "Перепробег, км",
        "initial_mileage": "Пробег при выдаче",
        "issued_at": "Дата выдачи",
        "equipment": "Комплектность",
        "damage": "Повреждения",
        "mileage": "Пробег",
        "fuel": "Топливо, %",
    }
    state_labels = {
        "active": "Действует",
        "confirmed": "Подтверждён",
        "completed": "Завершён",
        "draft": "Черновик",
        "bought": "Выкуплен",
        "approved": "Утверждён",
        "paid": "Выплачен",
    }
    if "status" in d:
        d["status"] = state_labels.get(d["status"], d["status"])
    facts = "".join(
        f"<tr><td>{html.escape(labels[k])}</td><td>{html.escape(str(v))}</td></tr>" for k, v in d.items() if k in labels
    )
    table = ""
    if rows:
        keys = list(rows[0])
        table = (
            "<table><thead><tr>"
            + "".join("<th>" + html.escape(k) + "</th>" for k in keys)
            + "</tr></thead><tbody>"
            + "".join(
                "<tr>" + "".join("<td>" + html.escape(str(r.get(k, ""))) + "</td>" for k in keys) + "</tr>"
                for r in rows
            )
            + "</tbody></table>"
        )
    source = f'<html lang="ru"><meta charset="utf-8"><style>@page{{size:A4;margin:18mm}}body{{font:11px DejaVu Sans;color:#23272b}}h1{{font-size:24px}}table{{width:100%;border-collapse:collapse;margin:20px 0}}td,th{{padding:7px;border-bottom:1px solid #ddd;text-align:left;word-break:break-all}}th{{background:#f5ce43}}footer{{font-size:9px;color:#777}}</style><h1>Учебный таксопарк</h1><h2>Документ {html.escape(x.code)}</h2><p>Независимый демонстрационный проект. Учебные данные. Не является юридически значимым документом.</p><table>{facts}</table>{table}<footer>Сформирован из данных личной демосессии. Подтверждения сотрудников отражены в журнале событий.</footer></html>'
    return HTML(string=source).write_pdf()
