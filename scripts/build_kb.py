import json

from app.rag import build

print(json.dumps(build(), ensure_ascii=False))
