"""Operations: Redis for limits, cache and live events; Prometheus metrics; Sentry.

Redis is an accelerator, never the source of truth. Without it (no REDIS_URL, or it is down) limits fall back to
process memory, the cache is skipped and live events fall back to polling the database every two seconds. The job
queue stays in PostgreSQL (ADR 0002): a job and the ledger rows it writes commit in one transaction.
"""

import hashlib
import json
import os
import secrets
import time
from collections import deque
from datetime import datetime
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest
from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import event, func, select
from starlette.requests import Request
from starlette.responses import Response

from .db import Entry, Event, Item, Job, Session, System, Usage, db, now

PREFIX = "fleet:"
SALT = secrets.token_hex(8)  # per process: a hash cannot be matched back to an address after a restart
STATS = {"limited": 0, "allowed": 0, "cache_hit": 0, "cache_miss": 0, "published": 0}
RECENT: deque = deque(maxlen=3000)  # (route, ms, status, at) of the latest requests, for the console
ERRORS: deque = deque(maxlen=20)
_local: dict = {}
_state = {"client": None, "down_until": 0.0, "aclient": None}


# ---------------------------------------------------------------- Redis, with a short back-off when it is down


def redis():
    url = os.getenv("REDIS_URL")
    if not url or time.monotonic() < _state["down_until"]:
        return None
    if _state["client"] is None:
        import redis as lib

        _state["client"] = lib.Redis.from_url(url, socket_timeout=0.3, socket_connect_timeout=0.3, decode_responses=True)
    return _state["client"]


def _down():
    _state["down_until"] = time.monotonic() + 30


def aredis():
    url = os.getenv("REDIS_URL")
    if not url or time.monotonic() < _state["down_until"]:
        return None
    if _state["aclient"] is None:
        import redis.asyncio as alib

        _state["aclient"] = alib.Redis.from_url(url, socket_connect_timeout=0.3, decode_responses=True)
    return _state["aclient"]


# ---------------------------------------------------------------- who is asking, and how often


def client_ip(request: Request) -> str:
    """nginx appends the real peer to X-Forwarded-For; anything before it came from the client and is ignored."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def visitor(request: Request) -> str:
    return hashlib.sha256(f"{SALT}:{client_ip(request)}".encode()).hexdigest()[:16]


def allow(name: str, ident: str, limit: int, window: int) -> bool:
    """Fixed window counter: INCR + EXPIRE in Redis, a dictionary in process memory without it."""
    slot = int(time.time() // window)
    key = f"{PREFIX}rl:{name}:{ident}:{slot}"
    r = redis()
    count = None
    if r is not None:
        try:
            pipe = r.pipeline()
            pipe.incr(key)
            pipe.expire(key, window + 1)
            count = pipe.execute()[0]
        except Exception:
            _down()
    if count is None:
        if len(_local) > 5000:
            _local.clear()
        count = _local[key] = _local.get(key, 0) + 1
    ok = count <= limit
    STATS["allowed" if ok else "limited"] += 1
    return ok


# ---------------------------------------------------------------- cache, invalidated by a per-space generation


def generation(space: str) -> str:
    r = redis()
    if r is None:
        return ""
    try:
        return r.get(f"{PREFIX}gen:{space}") or "0"
    except Exception:
        _down()
        return ""


def cached(space: str, name: str, params, build):
    """Serve a report from Redis while nothing in the space has changed. Any commit that touches the space's items,
    ledger or events bumps its generation, so a stale answer is never served."""
    gen = generation(space)
    if not gen:
        return build(), False
    digest = hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:16]
    key = f"{PREFIX}cache:{space}:{gen}:{name}:{digest}"
    r = redis()
    try:
        hit = r.get(key) if r is not None else None
    except Exception:
        _down()
        hit = None
    if hit is not None:
        STATS["cache_hit"] += 1
        return json.loads(hit), True
    STATS["cache_miss"] += 1
    value = build()
    try:
        if r is not None:
            r.set(key, json.dumps(value, ensure_ascii=False, default=str), ex=300)
    except Exception:
        _down()
    return value, False


# ---------------------------------------------------------------- commits → generation bump and a live event


@event.listens_for(Session, "after_flush")
def _collect(session, _ctx):
    touched = session.info.setdefault("touched", set())
    live = session.info.setdefault("live", set())
    for obj in list(session.new) + list(session.dirty) + list(session.deleted):
        if isinstance(obj, Item | Entry | Event) and getattr(obj, "space", None):
            touched.add(obj.space)
            if isinstance(obj, Event) and obj in session.new:
                live.add(obj.space)


@event.listens_for(Session, "after_commit")
def _publish(session):
    touched, live = session.info.pop("touched", set()), session.info.pop("live", set())
    if not touched:
        return
    r = redis()
    if r is None:
        return
    try:
        pipe = r.pipeline()
        for space in touched:
            pipe.incr(f"{PREFIX}gen:{space}")
            pipe.expire(f"{PREFIX}gen:{space}", 86400)
        for space in live:
            pipe.publish(f"{PREFIX}events:{space}", "1")
        pipe.execute()
        STATS["published"] += len(live)
    except Exception:
        _down()


@event.listens_for(Session, "after_rollback")
def _forget(session):
    session.info.pop("touched", None)
    session.info.pop("live", None)


class Waiter:
    """One subscription per open SSE stream: wakes up the moment a new event is committed for the space, and falls
    back to a plain two-second sleep when Redis is not there."""

    def __init__(self, space: str):
        self.channel = f"{PREFIX}events:{space}"
        self.pubsub: Any = None
        self.mode = "poll"

    async def wait(self, timeout: float = 2.0):
        import asyncio

        if self.pubsub is None and (client := aredis()) is not None:
            try:
                self.pubsub = client.pubsub()
                await self.pubsub.subscribe(self.channel)
                self.mode = "redis"
            except Exception:
                self.pubsub = None
                _down()
        if self.pubsub is None:
            await asyncio.sleep(timeout)
            return
        try:
            await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=timeout)
        except Exception:
            await self.close()
            _down()
            await asyncio.sleep(timeout)

    async def close(self):
        if self.pubsub is not None:
            try:
                await self.pubsub.aclose()
            except Exception:
                pass
            self.pubsub = None


# ---------------------------------------------------------------- metrics

REGISTRY = CollectorRegistry()
REQUESTS = Counter("fleet_http_requests_total", "HTTP requests", ["method", "route", "status"], registry=REGISTRY)
LATENCY = Histogram("fleet_http_request_seconds", "HTTP request latency", ["method", "route"], registry=REGISTRY,
                    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10))
LIMITED = Counter("fleet_rate_limited_total", "Requests refused by a rate limit", ["name"], registry=REGISTRY)


def gauges():
    """Business and queue state read from PostgreSQL at scrape time, so the API and the worker agree."""
    with db() as s:
        worker = s.get(System, "worker")
        age = (now() - datetime.fromisoformat(worker.data["heartbeat"])).total_seconds() if worker else -1
        states = dict(s.execute(select(Job.state, func.count()).group_by(Job.state)).all())
        day = now().replace(hour=0, minute=0, second=0, microsecond=0)
        spend = s.scalar(select(func.coalesce(func.sum(Usage.cost), 0)).where(Usage.created >= day))
        calls = s.scalar(select(func.count()).select_from(Usage).where(Usage.created >= day))
        failed = s.scalar(select(func.count()).select_from(Job).where(Job.state == "failed", Job.due >= day))
        oldest = s.scalar(select(func.min(Job.due)).where(Job.state == "pending", Job.due <= now()))
    return {
        "worker_heartbeat_age_seconds": round(age, 1),
        "jobs": {k: int(v) for k, v in states.items()},
        "jobs_failed_today": int(failed or 0),
        "queue_wait_seconds": round((now() - oldest).total_seconds(), 1) if oldest else 0.0,
        "ai_spend_usd_today": float(spend or 0),
        "ai_calls_today": int(calls or 0),
    }


class _Business:
    def collect(self):
        g = gauges()
        yield GaugeMetricFamily("fleet_worker_heartbeat_age_seconds", "Seconds since the worker's heartbeat",
                                value=g["worker_heartbeat_age_seconds"])
        jobs = GaugeMetricFamily("fleet_jobs", "Jobs in the PostgreSQL queue by state", labels=["state"])
        for state, n in g["jobs"].items():
            jobs.add_metric([state], n)
        yield jobs
        yield GaugeMetricFamily("fleet_jobs_failed_today", "Jobs that ran out of attempts today", value=g["jobs_failed_today"])
        yield GaugeMetricFamily("fleet_queue_wait_seconds", "Age of the oldest due job", value=g["queue_wait_seconds"])
        yield GaugeMetricFamily("fleet_ai_spend_usd_today", "Model spend today, USD", value=g["ai_spend_usd_today"])
        yield GaugeMetricFamily("fleet_ai_calls_today", "Model calls today", value=g["ai_calls_today"])


REGISTRY.register(_Business())  # type: ignore[arg-type]


def metrics_response():
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


def route_of(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", None) or "unmatched"


def record(request: Request, status: int, seconds: float):
    route = route_of(request)
    if route in ("/metrics", "/api/v1/events"):
        return
    REQUESTS.labels(request.method, route, str(status)[0] + "xx").inc()
    LATENCY.labels(request.method, route).observe(seconds)
    RECENT.append((request.method + " " + route, round(seconds * 1000, 1), status, time.time()))
    if status >= 500:
        ERRORS.append({"route": request.method + " " + route, "status": status, "at": now().isoformat(timespec="seconds")})


def summary():
    """What the console shows: per-route latency over the last few thousand requests, Redis state, limits."""
    rows: dict = {}
    for route, ms, status, _ in RECENT:
        rows.setdefault(route, []).append((ms, status))
    routes = []
    for route, xs in rows.items():
        ms = sorted(x[0] for x in xs)
        routes.append({"route": route, "count": len(xs), "p50": ms[len(ms) // 2], "p95": ms[min(len(ms) - 1, int(len(ms) * 0.95))],
                       "errors": sum(1 for x in xs if x[1] >= 500)})
    routes.sort(key=lambda r: -r["count"])
    info = {"enabled": bool(os.getenv("REDIS_URL")), "ok": False}
    r = redis()
    if r is not None:
        try:
            t = time.perf_counter()
            r.ping()
            mem = r.info("memory")
            info.update(ok=True, ping_ms=round((time.perf_counter() - t) * 1000, 2), used_mb=round(mem["used_memory"] / 1048576, 1),
                        keys=r.dbsize())
        except Exception:
            _down()
    return {"routes": routes[:15], "requests": len(RECENT), "errors": list(ERRORS)[-10:], "redis": info, "stats": dict(STATS),
            "sentry": bool(os.getenv("SENTRY_DSN")), "queue": gauges()}


def init_sentry():
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return False
    import sentry_sdk

    sentry_sdk.init(dsn=dsn, traces_sample_rate=float(os.getenv("SENTRY_TRACES", "0.05")), send_default_pii=False,
                    environment=os.getenv("SENTRY_ENV", "demo"))
    return True
