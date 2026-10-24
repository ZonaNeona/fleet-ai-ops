"""Hermes Agent as one of the agent's executors: a turn is `POST /v1/runs` plus the SSE stream of its events.

Hermes (profile «fleet» on the host) reaches the stand's tools through the stand's own MCP server over HTTP, with a
server key. Before a run the turn is recorded — space, role, time — and the MCP server executes Hermes's calls in
that space under that role, with the same checks as the in-app agent. Turns therefore go one at a time.

Every tool event becomes a trace step with the time Hermes reported it; the model's usage becomes a Usage row, so the
daily AI budget covers Hermes too. A run over the time limit is stopped (`/v1/runs/{id}/stop`).
"""

import json
import os
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal

import httpx

from .db import System, Usage, db, now

TURN_KEY = "agent_turn"
TURN_TTL = 150  # seconds a recorded turn stays valid for the MCP server
RUN_TIMEOUT_S = 90
_lock = threading.Lock()


class HermesUnavailable(RuntimeError):
    """Not configured, busy or failed: the built-in loop answers instead."""


@dataclass
class Result:
    text: str
    model: str = ""
    tools: list[str] = field(default_factory=list)
    tokens: int = 0
    cost: Decimal = Decimal(0)


def configured() -> bool:
    return bool(os.getenv("HERMES_API_URL") and os.getenv("HERMES_API_KEY") and os.getenv("FLEET_HERMES_MCP_KEY"))


def _client(timeout) -> httpx.Client:
    return httpx.Client(base_url=os.environ["HERMES_API_URL"].rstrip("/"), timeout=timeout, trust_env=False,
                        headers={"Authorization": "Bearer " + os.environ["HERMES_API_KEY"]})


def _record_turn(space, role, job):
    with db() as s:
        row = s.get(System, TURN_KEY)
        data = {"space": space, "role": role, "job": job, "at": time.time()}
        if row:
            row.data = data
        else:
            s.add(System(key=TURN_KEY, data=data))


def _close_turn():
    with db() as s:
        row = s.get(System, TURN_KEY)
        if row:
            row.data = {**row.data, "at": 0}


def run(job, trace) -> Result:
    if not configured():
        raise HermesUnavailable("Hermes не настроен")
    if not _lock.acquire(timeout=20):
        raise HermesUnavailable("Hermes занят другим ходом")
    try:
        _record_turn(job.space, job.data["role"], job.id)
        return _turn(job, trace)
    finally:
        _close_turn()
        _lock.release()


def _turn(job, trace) -> Result:
    run_id = None
    started = time.monotonic()
    question = (f"[Роль пользователя: {job.data['role']}. Инструменты уже ограничены этой ролью.]\n"
                + job.data["prompt"][:2000])
    try:
        with _client(20) as c:
            r = c.post("/v1/runs", json={"input": question, "session_id": f"fleet-{job.space}-{job.data['role']}"})
            r.raise_for_status()
            run_id = str(r.json().get("run_id") or r.json().get("id"))
        trace.append({"step": "hermes", "title": "Hermes принял ход", "ms": round((time.monotonic() - started) * 1000),
                      "status": "success", "output": {"run": run_id}})
        result = _events(run_id, trace, started)
    except (httpx.HTTPError, ValueError, KeyError) as e:
        if run_id:
            _stop(run_id)
        raise HermesUnavailable("Hermes не ответил: " + type(e).__name__) from None
    with db() as s:
        s.add(Usage(space=job.space, model="hermes:" + (result.model or "?"), cost=result.cost, tokens=result.tokens,
                    ms=round((time.monotonic() - started) * 1000)))
    return result


def _preview(raw) -> object:
    """Hermes previews a tool result as MCP text, sometimes JSON inside a JSON string."""
    value = raw
    for _ in range(3):
        if isinstance(value, dict) and "result" in value:
            value = value["result"]
        if isinstance(value, str):
            try:
                value = json.loads(value)
                continue
            except ValueError:
                break
    return value if not isinstance(value, str) else value[:400]


def _events(run_id, trace, started) -> Result:
    opened: dict[str, float] = {}
    used: list[str] = []
    answer = ""
    deadline = time.monotonic() + RUN_TIMEOUT_S
    with _client(httpx.Timeout(RUN_TIMEOUT_S, connect=10)) as c, c.stream("GET", f"/v1/runs/{run_id}/events") as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if time.monotonic() > deadline:
                _stop(run_id)
                raise HermesUnavailable("Hermes не уложился во время")
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line[5:].strip())
            except ValueError:
                continue
            kind = event.get("event") or event.get("type")
            name = str(event.get("tool") or event.get("tool_name") or "").split("__")[-1]
            if kind == "tool.started" and name:
                opened[name] = time.monotonic()
                used.append(name)
            elif kind == "tool.completed" and name:
                began = opened.pop(name, time.monotonic())
                trace.append({"step": "tool", "title": name, "ms": round((time.monotonic() - began) * 1000),
                              "status": "denied" if event.get("error") else "success", "via": "hermes · MCP",
                              "arguments": event.get("arguments") or {}, "output": _preview(event.get("preview") or "")})
            elif kind == "message.delta":
                answer += str(event.get("delta") or "")
            elif kind == "run.completed":
                usage = event.get("usage") or {}
                model = str((event.get("runtime") or {}).get("model") or "")
                prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
                completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
                tokens = prompt + completion
                cost = Decimal(str(usage.get("cost") or usage.get("cost_usd") or 0)) or price(model, prompt, completion)
                trace.append({"step": "llm", "title": "Hermes · ответ", "model": model, "tokens": tokens,
                              "cost": str(cost), "ms": round((time.monotonic() - started) * 1000), "status": "success"})
                return Result(str(event.get("output") or answer).strip(), model, used, tokens, cost)
            elif kind in ("run.failed", "run.cancelled", "run.interrupted"):
                raise HermesUnavailable(str(event.get("error") or kind))
    raise HermesUnavailable("поток событий оборвался")


def price(model, prompt, completion) -> Decimal:
    """Hermes does not always report the cost: it is computed from the provider's published prices, as for own calls."""
    from .ai import models

    try:
        p = models()[model]["pricing"]
        return Decimal(str(p["prompt"])) * prompt + Decimal(str(p["completion"])) * completion
    except Exception:
        return Decimal(0)


def _stop(run_id):
    try:
        with _client(10) as c:
            c.post(f"/v1/runs/{run_id}/stop", json={})
    except httpx.HTTPError:
        pass


def health() -> dict:
    if not configured():
        return {"configured": False}
    try:
        t = time.monotonic()
        with _client(5) as c:
            c.get("/health").raise_for_status()
        return {"configured": True, "ok": True, "ms": round((time.monotonic() - t) * 1000), "at": now().isoformat()}
    except httpx.HTTPError:
        return {"configured": True, "ok": False}
