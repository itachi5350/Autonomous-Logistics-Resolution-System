import socket

import psycopg
from psycopg.types.json import Jsonb
from app import event_queue
from app.config import DATABASE_URL
from app.graph import graph

CONSUMER = f"worker-{socket.gethostname()}"


def handle(event: dict) -> None:
    case_id = f"case-{event['event_id']}"
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(
            "INSERT INTO cases (id, tracking_id, status) VALUES (%s, %s, 'open') ON CONFLICT (id) DO NOTHING",
            (case_id, event["tracking_id"]),
        )
        status = conn.execute("SELECT status FROM cases WHERE id = %s", (case_id,)).fetchone()[0]
    if status != "open":
        print(f"[worker] {case_id} is already '{status}', skipping")
        return

    print(f"[worker] investigating {case_id} ({event['tracking_id']}, {event['event_type']}, {event.get('hours_stuck')}h)")
    result = graph.invoke(
        {"event": event, "case_id": case_id, "attempts": 0},
        {"recursion_limit": 30},
    )

    order = result.get("order")
    decision = result.get("decision")
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(
            "UPDATE cases SET status = %s, decision = %s WHERE id = %s",
            ("decided" if decision else "failed_needs_human", Jsonb(decision) if decision else None, case_id),
        )
    if not order:
        print(f"[worker] {case_id}: could not load the order: {result.get('sql_error')}")
        return
    tools_used = sum(1 for m in result.get("messages", []) if m.type == "tool")
    print(f"[worker] {case_id}: {order['customer_name']} | {order['product_name']} | "
          f"{order['payment_method']} | paid Rs {order['amount_paid_inr']:,}")
    print(f"           offered      : {decision['offered_actions']}")
    print(f"           model picked : {decision['model_recommendation']}"
          f"{'  (model unavailable)' if decision['model_recommendation'] is None else ''}")
    print(f"           FINAL        : {decision['recommended_action']}"
          f"{'  <-- overridden by code' if decision['overridden'] else ''}")
    print(f"           reasoning    : {decision['reasoning']}")
    print(f"           tool calls   : {tools_used}, SQL attempts: {result['attempts']}")


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