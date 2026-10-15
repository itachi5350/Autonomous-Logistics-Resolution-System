import psycopg
from fastapi import FastAPI
from psycopg.types.json import Jsonb

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