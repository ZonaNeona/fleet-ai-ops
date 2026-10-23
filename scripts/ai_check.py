import json
from app.ai import models, candidates

try:
    available = models()
    print(
        json.dumps(
            {"candidates": [{"id": m, "pricing": available[m].get("pricing")} for m in candidates()]},
            ensure_ascii=False,
        )
    )
except Exception as e:
    print(
        json.dumps(
            {"error": type(e).__name__, "status": getattr(getattr(e, "response", None), "status_code", None)}
        )
    )
