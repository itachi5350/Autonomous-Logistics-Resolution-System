"""The money-moving code. Plain code, no LLM: an approved decision is carried out exactly once."""
import httpx
import psycopg
from psycopg.types.json import Jsonb
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from app import policy
from app.config import ACTION_MAX_ATTEMPTS, ACTION_TIMEOUT_SECONDS, DATABASE_URL, MOCK_API_URL

ENDPOINTS = {"refund": "/refunds", "replacement": "/replacements", "cancel": "/cancellations"}


def idempotency_key(case_id: str, action: str) -> str:
    # Derived from the case and the action, NEVER random. A retry, a crash-and-rerun and a
    # redelivered message must all send the SAME key, or the provider would pay twice.
    return f"{case_id}:{action}"


def _is_transient(err: BaseException) -> bool:
    if isinstance(err, httpx.TransportError):          # timeouts, connection refused or reset
        return True
    if isinstance(err, httpx.HTTPStatusError):
        return err.response.status_code in (429, 502, 503, 504)
    return False                                       # 400, 409, 422...: our request is wrong, retrying won't help


def _log_retry(state) -> None:
    print(f"[action] attempt {state.attempt_number} failed ({state.outcome.exception()!r}), retrying")


def _call_provider(action: str, order_id: int, amount_inr: int, key: str, counter: dict) -> dict:
    def once() -> dict:
        counter["n"] += 1
        response = httpx.post(
            f"{MOCK_API_URL}{ENDPOINTS[action]}",
            json={"order_id": order_id, "amount_inr": amount_inr},
            headers={"Idempotency-Key": key},
            timeout=ACTION_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()

    retryer = Retrying(
        stop=stop_after_attempt(ACTION_MAX_ATTEMPTS),
        wait=wait_exponential_jitter(initial=0.5, max=8),
        retry=retry_if_exception(_is_transient),
        before_sleep=_log_retry,
        reraise=True,                                  # after the last attempt, raise the real error
    )
    return retryer(once)


def _record_failure(case_id: str, action: str, key: str, attempts: int, error: str) -> dict:
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(
            "INSERT INTO actions (case_id, action_type, idempotency_key, status, attempts, last_error) "
            "VALUES (%s, %s, %s, 'failed', %s, %s) ON CONFLICT (idempotency_key) DO UPDATE SET "
            "status = 'failed', attempts = actions.attempts + EXCLUDED.attempts, last_error = EXCLUDED.last_error",
            (case_id, action, key, attempts, error),
        )
    return {"ok": False, "attempts": attempts, "error": error, "idempotency_key": key}


def run_action(case_id: str, order: dict, action: str, approved_payout: int) -> dict:
    """Carry out ONE approved action. Safe to call again for the same case: the key never changes."""
    key = idempotency_key(case_id, action)

    # 1. Pay exactly what was approved. Recompute from the database, never trust a stale number.
    current = policy.payout_inr(action, policy.estimate_costs(order["order_id"]))
    if current != approved_payout:
        return _record_failure(case_id, action, key, 0,
                               f"amount changed since approval (approved Rs {approved_payout}, now Rs {current})")

    with psycopg.connect(DATABASE_URL) as conn:
        # 2. Already done earlier (crash after success, redelivered message)? Do not call the provider again.
        row = conn.execute(
            "SELECT api_result FROM actions WHERE idempotency_key = %s AND status = 'succeeded'", (key,)
        ).fetchone()
        if row:
            return {"ok": True, "attempts": 0, "replayed": True, "idempotency_key": key,
                    "provider_id": row[0]["id"], "amount_inr": row[0]["amount_inr"]}
        # 3. Write the intent BEFORE touching money.
        conn.execute(
            "INSERT INTO actions (case_id, action_type, idempotency_key, status) "
            "VALUES (%s, %s, %s, 'pending') ON CONFLICT (idempotency_key) DO NOTHING",
            (case_id, action, key),
        )

    counter = {"n": 0}
    try:
        result = _call_provider(action, order["order_id"], current, key, counter)
    except Exception as err:
        first_line = (str(err).splitlines() or [""])[0]
        return _record_failure(case_id, action, key, counter["n"], f"{type(err).__name__}: {first_line}"[:300])

    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(
            "UPDATE actions SET status = 'succeeded', api_result = %s, attempts = actions.attempts + %s, last_error = NULL "
            "WHERE idempotency_key = %s",
            (Jsonb(result), counter["n"], key),
        )
    return {"ok": True, "attempts": counter["n"], "replayed": False, "idempotency_key": key,
            "provider_id": result["id"], "amount_inr": result["amount_inr"]}