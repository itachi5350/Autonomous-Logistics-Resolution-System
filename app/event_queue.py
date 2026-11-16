import json

import redis

from app.config import REDIS_URL

STREAM = "shipping-events"
GROUP = "case-workers"
DEAD_STREAM = "dead-letters"
FAILURES_KEY = "message-failures"      # hash: message id -> how many times it failed

r = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def publish(event: dict) -> str:
    return r.xadd(STREAM, {"event": json.dumps(event)})


def ensure_group() -> None:
    try:
        r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except redis.ResponseError as err:
        if "BUSYGROUP" not in str(err):  # group already exists: fine
            raise


def read(consumer: str, pending: bool = False, block_ms: int = 5000) -> list[tuple[str, dict]]:
    """New messages, or (pending=True) messages already delivered to this worker but never acknowledged."""
    try:
        resp = r.xreadgroup(
            GROUP, consumer, {STREAM: "0" if pending else ">"},
            count=100, block=None if pending else block_ms,
        )
    except redis.TimeoutError:
        return []
    messages = []
    for _stream, entries in resp or []:
        for msg_id, fields in entries:
            messages.append((msg_id, json.loads(fields["event"])))
    return messages


def ack(msg_id: str) -> None:
    r.xack(STREAM, GROUP, msg_id)


# ---------- Phase 5b: failure counting and the dead-letter list ----------
def record_failure(msg_id: str) -> int:
    """Stored in Redis, so the count survives a worker restart."""
    return int(r.hincrby(FAILURES_KEY, msg_id, 1))


def clear_failures(msg_id: str) -> None:
    r.hdel(FAILURES_KEY, msg_id)


def dead_letter(msg_id: str, event: dict, error: str) -> None:
    """Park a message that keeps failing, then acknowledge it so it stops coming back."""
    r.xadd(DEAD_STREAM, {"event": json.dumps(event), "error": error[:500], "original_id": msg_id})
    r.xack(STREAM, GROUP, msg_id)
    r.hdel(FAILURES_KEY, msg_id)


def list_dead_letters(count: int = 50) -> list[tuple[str, dict]]:
    return r.xrange(DEAD_STREAM, count=count)


def requeue_dead_letter(dead_id: str) -> bool:
    entries = r.xrange(DEAD_STREAM, min=dead_id, max=dead_id)
    if not entries:
        return False
    publish(json.loads(entries[0][1]["event"]))
    r.xdel(DEAD_STREAM, dead_id)
    return True