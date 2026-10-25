"""The incoming-document pipeline as a LangGraph state machine.

    START → read → classify → validate ─┬─ all checks pass, confident ─────────────→ post → END
                                        └─ anything off → review ── interrupt() ─┬─ approve → post → END
                                                                                 └─ reject → reject → END

`review` calls `interrupt()`: the run stops and its state is checkpointed in PostgreSQL (schema `langgraph`).
A person decides in the cabinet minutes or days later; the worker resumes the same thread. The document
itself lives in `items` — the graph state only carries its id and the decision. Step timings are measured.

Run by the worker as a short subprocess:  python -m app.inbox_graph run|approve|reject <doc id>...
"""

import os
import sys
import time
from typing import Literal, TypedDict

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from psycopg.rows import dict_row
from sqlalchemy.orm.attributes import flag_modified

from . import inbox
from .db import Item, Space, db, now
from .domain import audit

LABELS = dict(inbox.STEPS)
ORDER = [n for n, _ in inbox.STEPS] + ["reject"]


class State(TypedDict, total=False):
    doc: str
    decision: str


def _step(d, node, status, ms=None, note=""):
    steps = [x for x in d.get("steps", []) if x["node"] != node]
    steps.append(
        {
            "node": node,
            "label": LABELS.get(node, "Отклонено"),
            "status": status,
            "ms": round(ms) if ms is not None else None,
            "note": note,
        }
    )
    d["steps"] = sorted(steps, key=lambda x: ORDER.index(x["node"]) if x["node"] in ORDER else 99)


def _save(s, doc, d, title=None):
    # A fresh dict every time: queries inside a step autoflush, and later in-place edits would be lost.
    doc.data = {**d}
    flag_modified(doc, "data")
    doc.version += 1
    if title:
        audit(s, s.get(Space, doc.space), title, doc.id, via="inbox")


def node_read(state: State) -> State:
    started = time.perf_counter()
    with db() as s:
        doc = s.get(Item, state["doc"])
        d = {**doc.data, "status": "reading"}
        try:
            text, images, how = inbox.load_source(doc.space, d)
            if text:
                d["engine"], d["read_note"] = "rules", how
                d["kind"], d["values"], d["confidence"] = inbox.by_rules(text)
                note = f"{how}: {len(text)} символов"
            else:
                kind, values, confidence, summary, meta = inbox.by_model(doc.space, images)
                d.update(
                    engine="model",
                    read_note=how,
                    kind=kind,
                    values=values,
                    confidence=confidence,
                    summary=summary,
                    model=meta["model"],
                    cost=meta["cost"],
                )
                note = f"{how} → {meta['model'].split('/')[-1]}, ${float(meta['cost']):.4f}"
            _step(d, "read", "done", (time.perf_counter() - started) * 1000, note)
        except Exception as exc:
            d["status"] = "failed"
            d["decision"] = str(exc)[:300]
            _step(d, "read", "error", (time.perf_counter() - started) * 1000, str(exc)[:160])
        _save(s, doc, d)
    return {}


def after_read(state: State) -> Literal["classify", "__end__"]:
    with db() as s:
        return "__end__" if s.get(Item, state["doc"]).data["status"] == "failed" else "classify"


def node_classify(state: State) -> State:
    started = time.perf_counter()
    with db() as s:
        doc = s.get(Item, state["doc"])
        d = dict(doc.data)
        values = d.get("values") or {}
        found = sum(1 for k, _ in inbox.FIELDS[d["kind"]] if values.get(k))
        how = "по ответу модели" if d.get("engine") == "model" else "правила"
        _step(
            d,
            "classify",
            "done",
            (time.perf_counter() - started) * 1000,
            f"{inbox.KINDS[d['kind']]} · {how}: {found} полей, уверенность {d.get('confidence', 0):.2f}",
        )
        _save(s, doc, d)
    return {}


def node_validate(state: State) -> State:
    started = time.perf_counter()
    with db() as s:
        doc = s.get(Item, state["doc"])
        d = {**doc.data, "status": "checking"}
        doc.data = d
        checks, links = inbox.run_checks(s, doc)
        failed = [c for c in checks if not c["ok"]]
        ms = (time.perf_counter() - started) * 1000
        d.update(checks=checks, links=links)
        if failed:
            money = any(c["label"] == "Сумма в пределах сметы" for c in failed)
            d["status"] = "mismatch" if money else "review"
            _step(d, "validate", "error", ms, f"не пройдено: {len(failed)} из {len(checks)}")
            _step(d, "review", "active", None, "ждёт решения")
        elif d.get("confidence", 0) < inbox.CONFIDENT:
            d["status"] = "review"
            _step(d, "validate", "done", ms, f"все {len(checks)} проверок пройдены")
            _step(d, "review", "active", None, f"поля прочитаны неуверенно ({d.get('confidence', 0):.2f})")
        else:
            d["status"] = "posting"
            _step(d, "validate", "done", ms, f"все {len(checks)} проверок пройдены")
            _step(d, "review", "skipped", None, "не нужно — всё сошлось")
        _save(s, doc, d, f"{doc.code}: ждёт решения" if d["status"] in ("review", "mismatch") else None)
    return {}


def after_validate(state: State) -> Literal["post", "review"]:
    with db() as s:
        return "review" if s.get(Item, state["doc"]).data["status"] in ("review", "mismatch") else "post"


def node_review(state: State) -> State:
    decision = interrupt({"doc": state["doc"]})
    return {"decision": str(decision)}


def after_review(state: State) -> Literal["post", "reject"]:
    return "post" if state.get("decision") == "approve" else "reject"


def node_post(state: State) -> State:
    started = time.perf_counter()
    by_person = state.get("decision") == "approve"
    with db() as s:
        doc = s.get(Item, state["doc"], with_for_update=True)
        d = dict(doc.data)
        doc.data = d
        try:
            what = inbox.post_document(s, doc, by_person)
            d = {**doc.data, "links": doc.data.get("links", {})}
            d.update(
                status="posted",
                posted_at=now().isoformat(),
                result=what,
                decision="Подтверждено человеком" if by_person else "Проведено автоматически: все проверки пройдены",
            )
            if by_person:
                _step(d, "review", "done", None, "подтверждено")
            _step(d, "post", "done", (time.perf_counter() - started) * 1000, what)
            _save(s, doc, d, f"{doc.code}: {what}")
        except Exception as exc:
            s.rollback()
            doc = s.get(Item, state["doc"])
            reason = str(getattr(exc, "detail", "") or exc)[:200]
            d = {**doc.data, "status": "failed", "decision": f"Проводка не прошла: {reason}"}
            _step(d, "post", "error", (time.perf_counter() - started) * 1000, reason)
            _save(s, doc, d)
    return {}


def node_reject(state: State) -> State:
    with db() as s:
        doc = s.get(Item, state["doc"])
        d = {**doc.data, "status": "rejected", "decision": "Отклонено: запрошен исправленный документ"}
        _step(d, "review", "done", None, "отклонено")
        _step(d, "post", "skipped", None, "не проводится")
        _save(s, doc, d)
    return {}


def build(checkpointer=None):
    g = StateGraph(State)
    for name, fn in [
        ("read", node_read),
        ("classify", node_classify),
        ("validate", node_validate),
        ("review", node_review),
        ("post", node_post),
        ("reject", node_reject),
    ]:
        g.add_node(name, fn)
    g.add_edge(START, "read")
    g.add_conditional_edges("read", after_read)
    g.add_edge("classify", "validate")
    g.add_conditional_edges("validate", after_validate)
    g.add_conditional_edges("review", after_review)
    g.add_edge("post", END)
    g.add_edge("reject", END)
    return g.compile(checkpointer=checkpointer)


def connect():
    dsn = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute("CREATE SCHEMA IF NOT EXISTS langgraph")
    conn = psycopg.connect(
        dsn, autocommit=True, prepare_threshold=0, row_factory=dict_row, options="-c search_path=langgraph"
    )
    saver = PostgresSaver(conn)
    saver.setup()
    return conn, saver


def main(action, ids):
    conn, saver = connect()
    try:
        app = build(saver)
        with db() as s:
            ids = [i for i in ids if s.get(Item, i)]  # the visitor's space may have expired meanwhile
        for doc_id in ids:
            config = {"configurable": {"thread_id": "inbox-" + doc_id}}
            if action == "run":
                app.invoke({"doc": doc_id}, config)
            else:
                app.invoke(Command(resume=action), config)
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("run", "approve", "reject"):
        raise SystemExit("usage: python -m app.inbox_graph run|approve|reject <doc id>...")
    main(sys.argv[1], sys.argv[2:])
