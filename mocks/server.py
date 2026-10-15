import os
import random
import uuid

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


class PayoutRequest(BaseModel):
    order_id: int
    amount_inr: int = Field(ge=0)


def create_app(chaos_rate: float = 0.2, seed: int | None = None, fail_after_commit: bool = False) -> FastAPI:
    app = FastAPI(title="Mock carrier and refund APIs")
    rng = random.Random(seed)
    ledger: list[dict] = []       # every payout that really happened
    by_key: dict[str, dict] = {}  # "kind:idempotency_key" -> stored result

    def roll_failure() -> bool:
        return rng.random() < chaos_rate

    def unavailable() -> HTTPException:
        return HTTPException(status_code=503, detail="Service Unavailable (chaos)", headers={"Retry-After": "5"})

    @app.get("/carrier/shipments/{tracking_id}")
    def carrier_status(tracking_id: str):
        if roll_failure():
            raise unavailable()
        return {"tracking_id": tracking_id, "carrier_status": "in_transit", "last_scan": "Bengaluru Hub"}

    def payout(kind: str, body: PayoutRequest, idempotency_key: str | None):
        if not idempotency_key:
            raise HTTPException(status_code=400, detail="Idempotency-Key header is required")

        scoped_key = f"{kind}:{idempotency_key}"  # refunds and replacements never share a key

        failing = roll_failure()
        if failing and not fail_after_commit:
            raise unavailable()  # failed before doing anything

        if scoped_key in by_key:
            result = by_key[scoped_key]  # replay: same answer, no second payout
            if result["order_id"] != body.order_id or result["amount_inr"] != body.amount_inr:
                raise HTTPException(status_code=409, detail="Idempotency key reused with different request data")
        else:
            result = {
                "id": f"{kind[:3]}_{uuid.uuid4().hex[:8]}",
                "type": kind,
                "order_id": body.order_id,
                "amount_inr": body.amount_inr,
                "idempotency_key": idempotency_key,
            }
            by_key[scoped_key] = result
            ledger.append(result)

        if failing and fail_after_commit:
            raise unavailable()  # payout recorded, but the caller sees a 503
        return result

    @app.post("/refunds")
    def create_refund(body: PayoutRequest, idempotency_key: str | None = Header(default=None)):
        return payout("refund", body, idempotency_key)

    @app.post("/replacements")
    def create_replacement(body: PayoutRequest, idempotency_key: str | None = Header(default=None)):
        return payout("replacement", body, idempotency_key)

    @app.get("/_debug/ledger")  # never fails; lets you check for duplicate payouts
    def get_ledger():
        return {"count": len(ledger), "payouts": ledger}

    return app


app = create_app(chaos_rate=float(os.getenv("CHAOS_RATE", "0.2")))