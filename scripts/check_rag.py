import json, resource
from app.rag import search, catalog

queries = [
    "Какие документы нужны водителю?",
    "Что делать при ДТП?",
    "Как вернуть залог?",
    "Сколько будет стоить досрочный выкуп?",
    "Как приготовить борщ?",
    "Какова масса Юпитера?",
    "Сколько я должен?",
]
out = []
for q in queries:
    r = search(q)
    out.append(
        {
            "query": q,
            "hits": [
                {k: c[k] for k in ("id", "title", "cosine", "rrf")}
                for c in r["chunks"][:3]
            ],
            "accepted": len(r["accepted"]),
        }
    )
print(
    json.dumps(
        {
            "catalog": catalog(),
            "results": out,
            "rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        },
        ensure_ascii=False,
        indent=2,
    )
)
