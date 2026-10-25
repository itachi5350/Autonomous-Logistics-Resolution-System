import secrets
import socket
import time

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from psycopg.types.json import Jsonb

from app import event_queue
from app.config import DATABASE_URL, MAX_CUSTOMER_ASKS, PACE_SECONDS
from app.graph import build_graph

CONSUMER = f"worker-{socket.gethostname()}"


def run_config(case_id: str) -> dict:
    # thread_id is the key the checkpointer saves this case's state under
    return {"configurable": {"thread_id": case_id}, "recursion_limit": 30}


def update_case(case_id: str, status: str, decision: dict | None = None) -> None:
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(
            "UPDATE cases SET status = %s, decision = COALESCE(%s, decision) WHERE id = %s",
            (status, Jsonb(decision) if decision else None, case_id),
        )


def case_status(case_id: str) -> str | None:
    with psycopg.connect(DATABASE_URL) as conn:
        row = conn.execute("SELECT status FROM cases WHERE id = %s", (case_id,)).fetchone()
    return row[0] if row else None


def print_decision(case_id: str, values: dict) -> None:
    order, decision = values["order"], values["decision"]
    tools_used = sum(1 for m in values.get("messages", []) if m.type == "tool")
    print(f"[worker] {case_id}: {order['customer_name']} | {order['product_name']} | "
          f"{order['payment_method']} | paid Rs {order['amount_paid_inr']:,}")
    print(f"           offered      : {decision['offered_actions']}")
    print(f"           model picked : {decision['model_recommendation']}"
          f"{'  (model unavailable)' if decision['model_recommendation'] is None else ''}")
    print(f"           FINAL        : {decision['recommended_action']}"
          f"{'  <-- overridden by code' if decision['overridden'] else ''}")
    print(f"           reasoning    : {decision['reasoning']}")
    print(f"           tool calls   : {tools_used}, SQL attempts: {values.get('attempts')}")


def save_pause(case_id: str, decision: dict, payload: dict) -> None:
    """Paused at the customer question. Store what the customer was asked and print the 'email'."""
    message = f"{payload['subject']}\n\n{payload['body']}"
    new_token = secrets.token_urlsafe(16)
    with psycopg.connect(DATABASE_URL) as conn:
        token = conn.execute(
            "UPDATE cases SET status = 'awaiting_customer', decision = %s, options = %s, "
            "customer_message = %s, reply_token = COALESCE(reply_token, %s) WHERE id = %s "
            "RETURNING reply_token",
            (Jsonb(decision), Jsonb(payload["options"]), message, new_token, case_id),
        ).fetchone()[0]
    print(f"[worker] {case_id}: waiting for the customer. Email that would be sent:")
    print("  ------------------------------------------------")
    for line in message.splitlines():
        print(f"  | {line}")
    print("  ------------------------------------------------")
    print(f'  simulate the customer:  python scripts/reply.py {case_id} {token} "your reply here"')


def save_manager_pause(case_id: str, payload: dict) -> None:
    """Paused at the manager gate: the payout is above the limit."""
    new_token = secrets.token_urlsafe(16)
    with psycopg.connect(DATABASE_URL) as conn:
        token = conn.execute(
            "UPDATE cases SET status = 'awaiting_approval', customer_choice = %s, "
            "customer_replied_at = COALESCE(customer_replied_at, now()), action_amount_inr = %s, "
            "approval_token = COALESCE(approval_token, %s) WHERE id = %s RETURNING approval_token",
            (payload["chosen_action"], payload["payout_inr"], new_token, case_id),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO approvals (case_id, status) VALUES (%s, 'pending') ON CONFLICT (case_id) DO NOTHING",
            (case_id,),
        )
    print(f"[worker] {case_id}: customer chose '{payload['chosen_action']}' "
          f"({payload['customer']}, {payload['product']}).")
    print(f"           payout Rs {payload['payout_inr']:,} is above the Rs {payload['threshold_inr']:,} limit "
          f"-> needs manager approval")
    print(f'  simulate the manager:  python scripts/manager.py {case_id} {token} approve "looks fine"')
    print(f'                     or: python scripts/manager.py {case_id} {token} reject "too risky"')


def save_outcome(case_id: str, values: dict) -> None:
    """The graph finished with an approval decision (automatic or by the manager)."""
    approval, choice = values["approval"], values["customer_choice"]
    payout = values.get("payout_inr", 0)
    approved = approval["approved"]
    status = "approved" if approved else "rejected"
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(
            "UPDATE cases SET status = %s, customer_choice = %s, final_action = %s, action_amount_inr = %s, "
            "customer_replied_at = COALESCE(customer_replied_at, now()) WHERE id = %s",
            (status, choice, choice if approved else None, payout, case_id),
        )
        conn.execute(
            "INSERT INTO approvals (case_id, status, approver, comment, decided_at) "
            "VALUES (%s, %s, %s, %s, now()) ON CONFLICT (case_id) DO UPDATE SET "
            "status = EXCLUDED.status, approver = EXCLUDED.approver, comment = EXCLUDED.comment, "
            "decided_at = EXCLUDED.decided_at",
            (case_id, status, approval["approver"], approval["note"]),
        )
    who = "automatically" if approval.get("auto") else f"by {approval['approver']}"
    print(f"[worker] {case_id}: {status.upper()} {who}: '{choice}', payout Rs {payout:,}. Note: {approval['note']}")
    if approved:
        print("           Next phase: the Action agent carries it out.")
    else:
        print("           Rejected: a human needs to follow up (Phase 5 will route this).")


def finish(case_id: str, graph, result: dict) -> None:
    """Called after every invoke: the graph is either paused or finished."""
    values = graph.get_state(run_config(case_id)).values
    order, decision = values.get("order"), values.get("decision")
    if not order or not decision:
        update_case(case_id, "failed_needs_human", decision)
        print(f"[worker] {case_id}: could not finish the investigation: {values.get('sql_error')}")
        return

    if "__interrupt__" in result:
        payload = result["__interrupt__"][0].value
        if payload.get("kind") == "manager_approval":
            save_manager_pause(case_id, payload)
        else:                                          # the customer question
            if values.get("asks", 0) == 0:             # first pause: show the decision too
                print_decision(case_id, values)
            save_pause(case_id, decision, payload)
        return

    if values.get("approval"):
        save_outcome(case_id, values)
    else:
        update_case(case_id, "failed_needs_human")
        print(f"[worker] {case_id}: reply still unclear after {MAX_CUSTOMER_ASKS} asks, handing to a human")


def handle_shipping_event(event: dict, graph) -> None:
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

    config = run_config(case_id)
    if graph.get_state(config).next:
        # A paused graph exists but the case is still 'open': we crashed between pausing and saving.
        update_case(case_id, "failed_needs_human")
        print(f"[worker] {case_id}: found a paused graph for an 'open' case, handing to a human")
        return

    print(f"[worker] investigating {case_id} ({event['tracking_id']}, {event['event_type']}, {event.get('hours_stuck')}h)")
    result = graph.invoke({"event": event, "case_id": case_id, "attempts": 0}, config)
    finish(case_id, graph, result)


def handle_customer_reply(msg: dict, graph) -> None:
    case_id = msg["case_id"]
    config = run_config(case_id)
    # Check the STATUS too: with two pauses, a stale reply could otherwise resume the wrong one.
    if case_status(case_id) != "awaiting_customer" or not graph.get_state(config).next:
        print(f"[worker] {case_id}: not waiting for a customer reply (duplicate or late), ignoring")
        return
    print(f"[worker] {case_id}: customer replied, resuming the graph")
    result = graph.invoke(Command(resume=msg["message"]), config)
    finish(case_id, graph, result)


def handle_manager_decision(msg: dict, graph) -> None:
    case_id = msg["case_id"]
    config = run_config(case_id)
    if case_status(case_id) != "awaiting_approval" or not graph.get_state(config).next:
        print(f"[worker] {case_id}: not waiting for approval (duplicate or late), ignoring")
        return
    print(f"[worker] {case_id}: manager decided, resuming the graph")
    resume = {"approved": msg["approved"], "approver": msg["approver"], "note": msg["note"]}
    result = graph.invoke(Command(resume=resume), config)
    finish(case_id, graph, result)


def process(msg_id: str, event: dict, graph) -> None:
    try:
        kind = event.get("kind")
        if kind == "customer_reply":
            handle_customer_reply(event, graph)
        elif kind == "manager_decision":
            handle_manager_decision(event, graph)
        else:
            handle_shipping_event(event, graph)
            if PACE_SECONDS:
                time.sleep(PACE_SECONDS)  # slow down the investigation to avoid hitting the LLM too fast
        event_queue.ack(msg_id)
    except Exception as err:
        print(f"[worker] failed on {msg_id}: {err!r} (not acknowledged, retried on restart)")


def main() -> None:
    event_queue.ensure_group()
    with PostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
        checkpointer.setup()                      # creates the checkpoint tables on first run
        graph = build_graph(checkpointer)
        print(f"[worker] {CONSUMER} waiting for events (Ctrl+C to stop)")
        for msg_id, event in event_queue.read(CONSUMER, pending=True):  # leftovers from a crash
            process(msg_id, event, graph)
        while True:
            for msg_id, event in event_queue.read(CONSUMER):
                process(msg_id, event, graph)


if __name__ == "__main__":
    main()