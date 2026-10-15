import socket

import psycopg

from app import event_queue
from app.config import DATABASE_URL

CONSUMER = f"worker-{socket.gethostname()}"


def handle(event: dict) -> None:
    case_id = f"case-{event['event_id']}"
    with psycopg.connect(DATABASE_URL) as conn:
        created = conn.execute(
            "INSERT INTO cases (id, tracking_id, status) VALUES (%s, %s, 'open') "
            "ON CONFLICT (id) DO NOTHING RETURNING id",
            (case_id, event["tracking_id"]),
        ).fetchone()
    if created is None:
        print(f"[worker] {case_id} already exists, skipping (duplicate delivery)")
        return
    print(f"[worker] opened {case_id} for {event['tracking_id']} "
          f"({event['event_type']}, {event.get('hours_stuck')}h)")
    # Phase 2: the LangGraph workflow starts here


def process(msg_id: str, event: dict) -> None:
    try:
        handle(event)
        event_queue.ack(msg_id)
    except Exception as err:
        print(f"[worker] failed on {msg_id}: {err!r} (not acknowledged, retried on restart)")


def main() -> None:
    event_queue.ensure_group()
    print(f"[worker] {CONSUMER} waiting for events (Ctrl+C to stop)")
    for msg_id, event in event_queue.read(CONSUMER, pending=True):  # leftovers from a crash
        process(msg_id, event)
    while True:
        for msg_id, event in event_queue.read(CONSUMER):
            process(msg_id, event)


if __name__ == "__main__":
    main()