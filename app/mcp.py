"""MCP server over the agent's tools: connect Claude Desktop, Cursor or any MCP client to the training fleet.

One registry: tools, descriptions and JSON schemas come from app/agent.py, so the in-app agent and an external
assistant see exactly the same tools under the same role checks. Writing tools only create drafts that a person
confirms in the cabinet.

Transports:
  * Streamable HTTP at POST /api/mcp — plain JSON responses, stateless. A visitor creates a personal key bound to their
    demo space (24 hours, role «owner»); `npx mcp-remote https://…/api/mcp?key=…` connects desktop clients.
  * stdio for local IDE agents:  FLEET_MCP_SPACE=<space id> python -m app.mcp
  * Hermes Agent (profile «fleet») connects over HTTP with a server key. Its tool calls run in the space and under the
    role of the turn the stand handed it (`app/hermes.py` records the turn before starting a run), so Hermes can do
    exactly what the visitor's own agent could — no more.
"""

import hashlib
import json
import os
import secrets
import sys
import time
from datetime import timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from .db import Space, System, db, now

router = APIRouter()
PROTOCOL = "2025-06-18"
ROLE = "owner"
CALLS_PER_MINUTE = 20
_hits: dict[str, list[float]] = {}


def tools(role=ROLE):
    from .agent import tools_for

    return [{"name": t["function"]["name"], "description": t["function"]["description"],
             "inputSchema": t["function"]["parameters"]} for t in tools_for(role)]


def handle(message, space, role=ROLE):
    """One JSON-RPC message → response dict, or None for notifications."""
    from .agent import execute

    mid, method = message.get("id"), message.get("method")
    if mid is None:
        return None  # notifications/initialized and friends need no answer

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    if method == "initialize":
        return ok({"protocolVersion": PROTOCOL, "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "fleet-ai-ops", "version": "1.0"},
                   "instructions": "Учебный таксопарк: автопарк, договоры, экономика машин, регламенты, Битрикс24. "
                                   "Данные учебные. Инструменты записи создают только черновики — их подтверждает человек в кабинете."})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": tools()})  # the full list: a call is still checked against the caller's role
    if method == "tools/call":
        params = message.get("params") or {}
        name, args = params.get("name"), params.get("arguments") or {}
        if not space:
            return ok({"content": [{"type": "text", "text": "Нет активного хода: инструменты вызываются только внутри вопроса посетителя."}],
                       "isError": True})
        try:
            result = execute(space, role, name, args, "mcp:" + hashlib.sha256(json.dumps([name, args, time.time()]).encode()).hexdigest()[:24])
            return ok({"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}], "isError": False})
        except Exception as e:
            reason = getattr(e, "detail", None) or str(e) or type(e).__name__
            return ok({"content": [{"type": "text", "text": str(reason)[:500]}], "isError": True})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Метод {method} не поддерживается"}}


def space_for_key(key):
    if not key or len(key) > 80:
        return None
    with db() as s:
        row = s.get(System, "mcp:" + hashlib.sha256(key.encode()).hexdigest()[:40])
        sp = s.get(Space, row.data["space"]) if row and row.data["expires"] >= now().isoformat() else None
        if not sp:
            return None
        sp.touched = now()  # an assistant working with the space keeps it alive like a visitor does
        return sp.id


def hermes_turn(key):
    """The server key of the stand's Hermes profile → (space, role) of the turn in progress, or None for any other key."""
    from .hermes import TURN_KEY, TURN_TTL

    expected = os.getenv("FLEET_HERMES_MCP_KEY", "")
    if not expected or not key or not secrets.compare_digest(key, expected):
        return None
    with db() as s:
        row = s.get(System, TURN_KEY)
        fresh = row and row.data.get("at", 0) > time.time() - TURN_TTL
        return (row.data["space"], row.data["role"]) if fresh else ("", ROLE)


def limited(key):
    t = time.monotonic()
    hits = [x for x in _hits.get(key, []) if t - x < 60]
    _hits[key] = hits + [t]
    return len(hits) >= CALLS_PER_MINUTE


@router.post("/api/mcp")
async def mcp_http(request: Request):
    key = request.query_params.get("key") or (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
    turn = hermes_turn(key)
    space, role = turn if turn else (space_for_key(key), ROLE)
    if not space and not turn:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "Нужен действующий ключ: создайте его в консоли «Под капотом» → MCP"}}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Некорректный JSON"}}, status_code=400)
    batch = body if isinstance(body, list) else [body]
    if len(batch) > 10:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Слишком большой пакет"}}, status_code=400)
    if any(m.get("method") == "tools/call" for m in batch if isinstance(m, dict)) and limited(key):
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32002, "message": f"Не больше {CALLS_PER_MINUTE} вызовов в минуту"}}, status_code=429)
    import anyio

    out = [r for r in [await anyio.to_thread.run_sync(handle, m, space, role) for m in batch if isinstance(m, dict)] if r]
    if not out:
        return Response(status_code=202)
    return JSONResponse(out if isinstance(body, list) else out[0], headers={"MCP-Protocol-Version": PROTOCOL})


@router.get("/api/mcp")
def mcp_get():
    # Stateless server: no server-initiated stream.
    return Response(status_code=405, headers={"Allow": "POST"})


@router.post("/api/v1/mcp/key")
def mcp_key(request: Request):
    from .api import auth

    with db() as s:
        sp = auth(s, request)
        key = "fl_" + secrets.token_urlsafe(24)
        s.add(System(key="mcp:" + hashlib.sha256(key.encode()).hexdigest()[:40],
                     data={"space": sp.id, "expires": (now() + timedelta(hours=24)).isoformat()}))
        return {"key": key, "expires_hours": 24, "role": ROLE}


@router.get("/api/v1/mcp/tools")
def mcp_tools():
    return {"tools": tools(), "protocol": PROTOCOL, "role": ROLE}


def stdio():
    """Line-delimited JSON-RPC over stdin/stdout for local IDE agents."""
    space = os.environ.get("FLEET_MCP_SPACE")
    with db() as s:
        if not space or not s.get(Space, space):
            raise SystemExit("FLEET_MCP_SPACE must point to an existing demo space")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            reply = handle(json.loads(line), space)
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Некорректный JSON"}}
        if reply:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    stdio()

