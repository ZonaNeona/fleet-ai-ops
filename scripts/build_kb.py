from app.rag import build
import json

print(json.dumps(build(), ensure_ascii=False))
