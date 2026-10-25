"""Inspectable mechanisms. Every session-specific read remains role scoped."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from .db import Event, Item, Job, db
from .domain import cansee

router = APIRouter()


class Question(BaseModel):
    prompt: str = Field(min_length=2, max_length=2000)


@router.get("/api/v1/under/kb")
def knowledge(request: Request):
    from .api import auth
    from .rag import catalog

    with db() as s:
        auth(s, request)
    return catalog()


@router.post("/api/v1/under/rag")
def rag_query(body: Question, request: Request):
    from .api import AIInput, ai

    return ai(AIInput(mode="rag", prompt=body.prompt), request)


@router.post("/api/v1/under/agent")
def agent_query(body: Question, request: Request):
    from .api import AIInput, ai

    return ai(AIInput(mode="agent", prompt=body.prompt), request)


@router.post("/api/v1/under/drafts/{id}/confirm")
def confirm_draft(id: str, request: Request):
    from .agent import confirm
    from .api import auth

    with db() as s:
        sp = auth(s, request)
        return confirm(s, sp, id)


@router.get("/api/v1/under/log")
def log(request: Request):
    from .api import auth

    with db() as s:
        sp = auth(s, request)
        rows = []
        jobs = s.scalars(
            select(Job).where(Job.space == sp.id, Job.data["role"].astext == sp.role).order_by(Job.due.desc()).limit(40)
        ).all()
        for j in jobs:
            rows.append(
                {
                    "id": j.id,
                    "at": j.due.isoformat(),
                    "type": j.kind,
                    "title": j.data.get("prompt", "Задание очереди")[:120],
                    "status": j.state,
                    "trace": j.result.get("trace", []),
                    "model": j.result.get("model"),
                    "cost": j.result.get("cost"),
                    "error": j.result.get("error"),
                }
            )
        for e in s.scalars(select(Event).where(Event.space == sp.id).order_by(Event.id.desc()).limit(80)):
            target = s.get(Item, e.target) if e.target else None
            webhook = e.data.get("channel") == "telegram"
            own_webhook = webhook and e.role == sp.role
            if (
                sp.role not in ("owner", "admin", "finance")
                and not own_webhook
                and (not target or not cansee(s, sp, target))
            ):
                continue
            rows.append(
                {
                    "id": "event-" + str(e.id),
                    "at": e.created.isoformat(),
                    "type": "webhook" if webhook else "event",
                    "title": e.title,
                    "status": "done",
                    "role": e.role,
                }
            )
        if sp.role in ("owner", "admin", "finance", "manager"):
            for x in s.execute(
                text("SELECT * FROM source_sync WHERE space=:space ORDER BY started DESC LIMIT 20"),
                {"space": sp.id},
            ).mappings():
                rows.append(
                    {
                        "id": x["id"],
                        "at": x["started"].isoformat(),
                        "type": "n8n",
                        "title": x["source"],
                        "status": x["status"],
                        "execution_id": x["execution_id"],
                        "trace": x["data"].get("trace", []),
                    }
                )
        return {
            "rows": sorted(rows, key=lambda r: r["at"], reverse=True)[:80],
            "scope": "Текущая демосессия и доступная роли история",
        }
