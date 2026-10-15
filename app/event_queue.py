import json

import redis

from app.config import REDIS_URL

STREAM = "shipping-events"
GROUP = "case-workers"

r = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=30)


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
        return []  # nothing arrived in time: the worker loop simply asks again
    messages = []
    for _stream, entries in resp or []:
        for msg_id, fields in entries:
            messages.append((msg_id, json.loads(fields["event"])))
    return messages


def ack(msg_id: str) -> None:
    r.xack(STREAM, GROUP, msg_id)