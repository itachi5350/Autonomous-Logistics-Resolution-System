"""Phase 6b: read-only dashboard API, plus demo controls that only exist when DEMO_MODE=1."""
import json
import time
from pathlib import Path

import httpx
import psycopg
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from app import event_queue
from app.config import DATABASE_URL, DEMO_MODE, MOCK_API_URL

router = APIRouter()
PAGE = Path(__file__).parent / "static" / "dashboard.html"
SECRET_COLUMNS = ("reply_token", "approval_token")   # never sent to the browser
NEEDS_HUMAN = ["failed_needs_human", "rejected"]

# One join gives every case a customer name and product name.
CASE_JOIN = """
FROM cases c
LEFT JOIN shipments s ON s.tracking_id = c.tracking_id
LEFT JOIN orders o ON o.id = s.order_id
LEFT JOIN customers cu ON cu.id = o.customer_id
LEFT JOIN products p ON p.sku = o.sku
"""


def query(sql: str, params=()) -> list[dict]:
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        return conn.execute(sql, params).fetchall()


# ---------------------------------------------------------------- the page
@router.get("/dashboard", include_in_schema=False)
def dashboard_page():
    return FileResponse(PAGE)


@router.get("/api/config")
def config():
    return {"demo": DEMO_MODE}


# ---------------------------------------------------------------- read-only data
@router.get("/api/cases")
def list_cases(status: str | None = None, limit: int = 100):
    limit = max(1, min(limit, 200))
    return query(
        "SELECT c.id, c.tracking_id, c.status, c.customer_choice, c.final_action, "
        "c.action_amount_inr, c.note, c.created_at, c.closed_at, "
        "cu.name AS customer, p.name AS product, "
        "c.decision->>'recommended_action' AS recommended "
        + CASE_JOIN +
        "WHERE (%(s)s::text IS NULL OR c.status = %(s)s) "
        "ORDER BY c.created_at DESC LIMIT %(n)s",
        {"s": status, "n": limit},
    )


@router.get("/api/cases/{case_id}")
def case_detail(case_id: str):
    rows = query("SELECT c.*, cu.name AS customer, p.name AS product " + CASE_JOIN + "WHERE c.id = %s", (case_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="case not found")
    case = {k: v for k, v in rows[0].items() if k not in SECRET_COLUMNS}
    return {
        "case": case,
        "actions": query("SELECT * FROM actions WHERE case_id = %s ORDER BY id", (case_id,)),
        "approval": (query("SELECT * FROM approvals WHERE case_id = %s", (case_id,)) or [None])[0],
        "calls": query(
            "SELECT agent, step, model, ok, retries, latency_ms, error, created_at "
            "FROM agent_calls WHERE case_id = %s ORDER BY created_at, id", (case_id,)),
    }


@router.get("/api/stats")
def stats(hours: int = 24):
    hours = max(1, min(hours, 24 * 30))
    return {
        "cases": query("SELECT status, count(*)::int AS n FROM cases GROUP BY status"),
        "actions": query(
            "SELECT status, count(*)::int AS n, coalesce(sum(attempts), 0)::int AS attempts "
            "FROM actions GROUP BY status"),
        "agents": query(
            "SELECT agent, step, model, count(*)::int AS calls, "
            "count(*) FILTER (WHERE NOT ok)::int AS failed, "
            "count(*) FILTER (WHERE retries > 0)::int AS retried, "
            "round(avg(latency_ms))::int AS avg_ms, "
            "(percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms))::int AS p50_ms, "
            "(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms))::int AS p95_ms "
            "FROM agent_calls WHERE created_at > now() - make_interval(hours => %s) "
            "GROUP BY agent, step, model ORDER BY agent, step", (hours,)),
        "hours": hours,
    }


@router.get("/api/needs-human")
def needs_human():
    cases = query(
        "SELECT c.id, c.status, c.customer_choice, c.action_amount_inr, c.note, "
        "a.status AS action_status, a.attempts, a.last_error "
        "FROM cases c LEFT JOIN actions a ON a.case_id = c.id "
        "WHERE c.status = ANY(%s) ORDER BY c.created_at DESC", (NEEDS_HUMAN,))
    dead, error = [], None
    try:
        for dead_id, fields in event_queue.list_dead_letters():
            try:
                event = json.loads(fields.get("event", "{}"))
            except ValueError:
                event = {"raw": fields.get("event")}
            dead.append({"id": dead_id, "error": fields.get("error"), "event": event})
    except Exception as exc:  # Redis down: the rest of the dashboard should still work
        error = str(exc)[:200]
    return {"cases": cases, "dead_letters": dead, "dead_letter_error": error}


@router.get("/api/ledger")
def ledger():
    """What the mock provider says it really paid out (proof that retries never paid twice)."""
    try:
        r = httpx.get(f"{MOCK_API_URL}/_debug/ledger", timeout=3)
        r.raise_for_status()
        return {"up": True, "payouts": r.json().get("payouts", [])}
    except Exception:
        return {"up": False, "payouts": []}


@router.get("/api/chaos")
def chaos_state():
    try:
        r = httpx.get(f"{MOCK_API_URL}/_debug/chaos", timeout=3)
        r.raise_for_status()
        return {"up": True, **r.json()}
    except Exception:
        return {"up": False}


# ---------------------------------------------------------------- demo controls (DEMO_MODE=1 only)
def need_demo() -> None:
    if not DEMO_MODE:
        raise HTTPException(status_code=404, detail="demo controls are off (set DEMO_MODE=1)")


def token_of(case_id: str, column: str) -> str:
    """Looked up on the server. The browser never sees a token."""
    assert column in SECRET_COLUMNS
    rows = query(f"SELECT {column} AS t FROM cases WHERE id = %s", (case_id,))
    if not rows or not rows[0]["t"]:
        raise HTTPException(status_code=404, detail="no token for this case (wrong state?)")
    return rows[0]["t"]


def call_self(request: Request, path: str, body: dict) -> dict:
    """Go through the SAME public endpoint a real customer or manager would use,
    so every check there (token, status) still applies."""
    url = str(request.base_url).rstrip("/") + path
    r = httpx.post(url, json=body, timeout=10)
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        raise HTTPException(status_code=r.status_code, detail=detail)
    return {"status": r.status_code}


class DemoEvent(BaseModel):
    tracking_id: str = Field(pattern=r"^TRK\d{3}$")
    hours_stuck: int = Field(default=75, ge=0, le=500)


class DemoReply(BaseModel):
    case_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1000)


class DemoManager(BaseModel):
    case_id: str = Field(min_length=1, max_length=100)
    approved: bool
    note: str = Field(default="", max_length=500)


class DemoCase(BaseModel):
    case_id: str = Field(min_length=1, max_length=100)


class DemoChaos(BaseModel):
    rate: float = Field(ge=0, le=1)
    after_commit: bool = False


@router.post("/api/demo/send-event")
def demo_send_event(body: DemoEvent, request: Request):
    need_demo()
    event = {"event_id": f"demo-{int(time.time() * 1000)}", "tracking_id": body.tracking_id,
             "event_type": "stuck_in_transit", "hours_stuck": body.hours_stuck}
    return call_self(request, "/webhook/shipping-update", event)


@router.post("/api/demo/reply")
def demo_reply(body: DemoReply, request: Request):
    need_demo()
    token = token_of(body.case_id, "reply_token")
    return call_self(request, f"/cases/{body.case_id}/reply", {"token": token, "message": body.message})


@router.post("/api/demo/manager")
def demo_manager(body: DemoManager, request: Request):
    need_demo()
    token = token_of(body.case_id, "approval_token")
    return call_self(request, f"/manager/cases/{body.case_id}/decision",
                     {"token": token, "approved": body.approved, "approver": "dashboard", "note": body.note})


@router.post("/api/demo/retry")
def demo_retry(body: DemoCase):
    need_demo()
    rows = query("SELECT status FROM cases WHERE id = %s", (body.case_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="case not found")
    if rows[0]["status"] != "failed_needs_human":
        raise HTTPException(status_code=409, detail=f"case is '{rows[0]['status']}', nothing to retry")
    event_queue.publish({"kind": "retry_action", "case_id": body.case_id})
    return {"status": "queued"}


@router.post("/api/demo/chaos")
def demo_chaos(body: DemoChaos):
    need_demo()
    try:
        r = httpx.post(f"{MOCK_API_URL}/_debug/chaos", json=body.model_dump(), timeout=5)
        r.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"mock provider not reachable: {str(exc)[:100]}")
    return r.json()