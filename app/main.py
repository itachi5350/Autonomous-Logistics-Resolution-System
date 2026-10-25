import psycopg
from fastapi import FastAPI, HTTPException
from psycopg.types.json import Jsonb
import secrets
from pydantic import BaseModel, Field
from app import event_queue
from app.config import DATABASE_URL
from app.models import ShippingEvent
from app.triage import triage

app = FastAPI(title="Logistics event ingest")


@app.post("/webhook/shipping-update", status_code=202)
def shipping_update(event: ShippingEvent):
    payload = event.model_dump()
    decision = triage(event)  # pure rules: no DB, no LLM

    with psycopg.connect(DATABASE_URL) as conn:
        inserted = conn.execute(
            "INSERT INTO shipping_events (event_id, tracking_id, event_type, payload) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (event_id) DO NOTHING RETURNING event_id",
            (event.event_id, event.tracking_id, event.event_type, Jsonb(payload)),
        ).fetchone()

        if inserted is None:
            return {"status": "duplicate"}

        if decision.open_case:
            event_queue.publish(payload)  # if this fails, the insert above is rolled back

    if not decision.open_case:
        return {"status": "ignored", "reason": decision.reason}
    return {"status": "queued", "reason": decision.reason}


@app.get("/health")
def health():
    return {"ok": True}

class CustomerReply(BaseModel):
    token: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1000)


@app.post("/cases/{case_id}/reply", status_code=202)
def customer_reply(case_id: str, body: CustomerReply):
    with psycopg.connect(DATABASE_URL) as conn:
        row = conn.execute("SELECT status, reply_token FROM cases WHERE id = %s", (case_id,)).fetchone()
    # Same 404 for "no such case" and "wrong token", so nobody can probe which case ids exist.
    if row is None or row[1] is None or not secrets.compare_digest(row[1].encode(), body.token.encode()):
        raise HTTPException(status_code=404, detail="case not found")
    if row[0] != "awaiting_customer":
        raise HTTPException(status_code=409, detail=f"case is '{row[0]}', not waiting for a reply")
    event_queue.publish({"kind": "customer_reply", "case_id": case_id, "message": body.message})
    return {"status": "accepted"}