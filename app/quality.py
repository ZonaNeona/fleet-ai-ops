"""Measured quality of retrieval: reference questions → the regulation that must be found, plus questions the
knowledge base must refuse. Free to run (local embeddings, no model call), so CI and every deploy run it.

    PYTHONPATH=. python -m app.quality        → reports/quality.json
"""

import json
import time
from pathlib import Path

from fastapi import APIRouter

from .db import now

router = APIRouter()
REPORT = Path(__file__).parent.parent / "reports" / "quality.json"

# question → expected knowledge-base document (file stem in app/kb); None means the system must refuse.
CASES = [
    ("Какие документы нужны водителю для работы в парке?", "driver-documents"),
    ("Что проверяют у кандидата в водители?", "driver-documents"),
    ("Что делать, если попал в аварию?", "accident"),
    ("Меня ударили на дороге, куда звонить?", "accident"),
    ("Когда возвращают залог после проката?", "deposit"),
    ("За что могут удержать депозит?", "deposit"),
    ("Кто платит штраф с камеры?", "fines"),
    ("Пришёл штраф ГИБДД по моей машине, что дальше?", "fines"),
    ("Как оформить досрочный выкуп автомобиля?", "buyout"),
    ("Можно ли взять каникулы по выкупу?", "buyout"),
    ("Как происходит выдача машины клиенту?", "issue-return"),
    ("Что проверяют при возврате автомобиля?", "issue-return"),
    ("Кто оплачивает ремонт машины?", "service"),
    ("Дадут ли подменный автомобиль на время ТО?", "service"),
    ("Как считается выплата владельцу автомобиля?", "owners"),
    ("Как посчитан мой долг по аренде?", "accounting"),
    ("Какие персональные данные хранит бот?", "privacy"),
    ("Как приготовить борщ?", None),
    ("Какова масса Юпитера?", None),
    ("Посоветуй хороший фильм на вечер", None),
]


def run():
    from .rag import search

    rows, started = [], time.perf_counter()
    for question, expected in CASES:
        t = time.perf_counter()
        r = search(question)
        docs = []
        for c in r["accepted"]:
            doc = c["id"].split(":")[0]  # chunk id is <document>:<n>
            if doc not in docs:
                docs.append(doc)
        if expected:
            rank = next((i + 1 for i, d in enumerate(docs) if d.startswith(expected)), None)
            ok1, ok3 = rank == 1, rank is not None and rank <= 3
        else:
            rank, ok1 = None, not docs
            ok3 = ok1
        rows.append({"question": question, "expected": expected, "found": docs[:3], "rank": rank,
                     "hit1": ok1, "hit3": ok3, "ms": round((time.perf_counter() - t) * 1000)})
    answerable = [x for x in rows if x["expected"]]
    refusals = [x for x in rows if not x["expected"]]
    report = {
        "at": now().isoformat(), "cases": len(rows),
        "retrieval": {
            "hit_at_1": round(sum(x["hit1"] for x in answerable) / len(answerable), 3),
            "hit_at_3": round(sum(x["hit3"] for x in answerable) / len(answerable), 3),
            "mrr": round(sum(1 / x["rank"] for x in answerable if x["rank"]) / len(answerable), 3),
            "refusals": round(sum(x["hit1"] for x in refusals) / len(refusals), 3),
            "ms_avg": round(sum(x["ms"] for x in rows) / len(rows)),
        },
        "rows": rows, "seconds": round(time.perf_counter() - started, 1),
        "method": "Эталонный вопрос засчитан, если нужный регламент среди принятых фрагментов (hit@1 — первым, hit@3 — в первой тройке). "
                  "Вопрос вне базы засчитан, если система ничего не приняла и модель не вызывалась.",
    }
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


@router.get("/api/v1/quality")
def quality():
    if not REPORT.exists():
        return {"retrieval": None}
    return json.loads(REPORT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    r = run()
    print(json.dumps(r["retrieval"], ensure_ascii=False))
