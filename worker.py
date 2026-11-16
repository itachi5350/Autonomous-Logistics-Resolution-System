import secrets
import socket
import time

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from psycopg.types.json import Jsonb

from app import actions, event_queue
from app.config import (DATABASE_URL, MAX_CUSTOMER_ASKS, MAX_MESSAGE_ATTEMPTS, PACE_SECONDS,
                        RETRY_PENDING_SECONDS)
from app.graph import build_graph, confirm_customer

CONSUMER = f"worker-{socket.gethostname()}"


def run_config(case_id: str) -> dict:
    # thread_id is the key the checkpointer saves this case's state under
    return {"configurable": {"thread_id": case_id}, "recursion_limit": 30}


def update_case(case_id: str, status: str, decision: dict | None = None, note: str | None = None) -> None:
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(
            "UPDATE cases SET status = %s, decision = COALESCE(%s, decision), note = %s WHERE id = %s",
            (status, Jsonb(decision) if decision else None, note, case_id),
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


def print_email_box(title: str, message: dict) -> None:
    print(f"  {title}")
    print("  ------------------------------------------------")
    for line in f"{message['subject']}\n\n{message['body']}".splitlines():
        print(f"  | {line}")
    print("  ------------------------------------------------")


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
    print_email_box(f"[worker] {case_id}: waiting for the customer. Email that would be sent:", payload)
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
    """The graph finished: rejected, or approved and the action was attempted."""
    approval, choice = values["approval"], values["customer_choice"]
    payout = values.get("payout_inr", 0)
    approved = approval["approved"]
    result = values.get("action_result") or {}
    note = None
    if not approved:
        status, note = "rejected", approval["note"] or "rejected"
    elif result.get("ok"):
        status = "resolved"
    else:
        status, note = "failed_needs_human", result.get("error")
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(
            "UPDATE cases SET status = %s, customer_choice = %s, final_action = %s, action_amount_inr = %s, "
            "note = %s, customer_replied_at = COALESCE(customer_replied_at, now()) WHERE id = %s",
            (status, choice, choice if approved else None, payout, note, case_id),
        )
        if status == "resolved":
            conn.execute("UPDATE cases SET closed_at = now() WHERE id = %s", (case_id,))
        conn.execute(
            "INSERT INTO approvals (case_id, status, approver, comment, decided_at) "
            "VALUES (%s, %s, %s, %s, now()) ON CONFLICT (case_id) DO UPDATE SET "
            "status = EXCLUDED.status, approver = EXCLUDED.approver, comment = EXCLUDED.comment, "
            "decided_at = EXCLUDED.decided_at",
            (case_id, "approved" if approved else "rejected", approval["approver"], approval["note"]),
        )
    who = "automatically" if approval.get("auto") else f"by {approval['approver']}"
    print(f"[worker] {case_id}: {'APPROVED' if approved else 'REJECTED'} {who}: '{choice}', "
          f"payout Rs {payout:,}. Note: {approval['note']}")
    if not approved:
        print("           Rejected: a human needs to follow up.")
    elif result.get("ok"):
        replay = " (already done earlier, not called again)" if result.get("replayed") else ""
        print(f"           ACTION DONE: {choice}, provider id {result['provider_id']}, "
              f"{result['attempts']} attempt(s){replay}")
        print(f"           status -> resolved. Idempotency key: {result['idempotency_key']}")
        if values.get("confirmation"):
            print_email_box(f"[worker] {case_id}: confirmation email that would be sent:", values["confirmation"])
    else:
        print(f"           ACTION FAILED after {result.get('attempts', 0)} attempt(s): {result.get('error')}")
        print("           status -> failed_needs_human. Retrying later with the SAME key is safe:")
        print(f"           python scripts/retry_action.py {case_id}")


def finish(case_id: str, graph, result: dict) -> None:
    """Called after every invoke: the graph is either paused or finished."""
    values = graph.get_state(run_config(case_id)).values
    order, decision = values.get("order"), values.get("decision")
    if not order or not decision:
        update_case(case_id, "failed_needs_human", decision, f"investigation failed: {values.get('sql_error')}")
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
        update_case(case_id, "failed_needs_human", note=f"customer reply unclear after {MAX_CUSTOMER_ASKS} asks")
        print(f"[worker] {case_id}: reply still unclear after {MAX_CUSTOMER_ASKS} asks, handing to a human")


def resume(case_id: str, graph, waiting_node: str, answer):
    """Give a paused graph its answer. If an earlier attempt already took the answer and then
    crashed, the graph is stopped at a different node: continue from there instead."""
    config = run_config(case_id)
    pending = graph.get_state(config).next
    if not pending:
        return None
    if pending[0] == waiting_node:
        return graph.invoke(Command(resume=answer), config)
    print(f"[worker] {case_id}: an earlier attempt stopped at '{pending[0]}', continuing from there")
    return graph.invoke(None, config)


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
    pending = graph.get_state(config).next
    if pending:
        if pending[0] in ("ask_customer", "ask_manager"):
            # Paused at a question but the case is still 'open': we crashed between pausing and saving.
            update_case(case_id, "failed_needs_human",
                        note="crashed between pausing and saving: the customer was never told")
            print(f"[worker] {case_id}: found a paused graph for an 'open' case, handing to a human")
            return
        print(f"[worker] {case_id}: an earlier run stopped at '{pending[0]}', continuing from there")
        result = graph.invoke(None, config)
        finish(case_id, graph, result)
        return

    print(f"[worker] investigating {case_id} ({event['tracking_id']}, {event['event_type']}, {event.get('hours_stuck')}h)")
    result = graph.invoke({"event": event, "case_id": case_id, "attempts": 0}, config)
    finish(case_id, graph, result)


def handle_customer_reply(msg: dict, graph) -> None:
    case_id = msg["case_id"]
    # Check the STATUS too: with several pauses, a stale reply could otherwise resume the wrong one.
    if case_status(case_id) != "awaiting_customer":
        print(f"[worker] {case_id}: not waiting for a customer reply (duplicate or late), ignoring")
        return
    print(f"[worker] {case_id}: customer replied, resuming the graph")
    result = resume(case_id, graph, "ask_customer", msg["message"])
    if result is None:
        print(f"[worker] {case_id}: no paused graph to resume, ignoring")
        return
    finish(case_id, graph, result)


def handle_manager_decision(msg: dict, graph) -> None:
    case_id = msg["case_id"]
    if case_status(case_id) != "awaiting_approval":
        print(f"[worker] {case_id}: not waiting for approval (duplicate or late), ignoring")
        return
    print(f"[worker] {case_id}: manager decided, resuming the graph")
    answer = {"approved": msg["approved"], "approver": msg["approver"], "note": msg["note"]}
    result = resume(case_id, graph, "ask_manager", answer)
    if result is None:
        print(f"[worker] {case_id}: no paused graph to resume, ignoring")
        return
    finish(case_id, graph, result)


def handle_retry_action(msg: dict, graph) -> None:
    """Re-run a failed action with the SAME idempotency key. If the provider already paid, it
    replays the saved result, so this can never pay twice."""
    case_id = msg["case_id"]
    if case_status(case_id) != "failed_needs_human":
        print(f"[worker] {case_id}: not in 'failed_needs_human', ignoring the retry request")
        return
    values = graph.get_state(run_config(case_id)).values
    approval = values.get("approval") or {}
    action, order, payout = values.get("customer_choice"), values.get("order"), values.get("payout_inr")
    if not (approval.get("approved") and action and order and payout is not None):
        print(f"[worker] {case_id}: there is no approved action to retry, ignoring")
        return

    print(f"[worker] {case_id}: re-running the {action} with the SAME idempotency key")
    result = actions.run_action(case_id, order, action, payout)
    if not result["ok"]:
        update_case(case_id, "failed_needs_human", note=result.get("error"))
        print(f"[worker] {case_id}: ACTION FAILED again after {result['attempts']} attempt(s): {result.get('error')}")
        return

    confirmation = confirm_customer(
        {"order": order, "action_result": result, "customer_choice": action, "case_id": case_id}
    )["confirmation"]
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(
            "UPDATE cases SET status = 'resolved', final_action = %s, action_amount_inr = %s, "
            "note = NULL, closed_at = now() WHERE id = %s",
            (action, payout, case_id),
        )
    replay = " (the provider had already done it: saved result returned, no second payout)" if result.get("replayed") else ""
    print(f"[worker] {case_id}: ACTION DONE on retry: {action}, provider id {result['provider_id']}, "
          f"{result['attempts']} attempt(s){replay}")
    print_email_box(f"[worker] {case_id}: confirmation email that would be sent:", confirmation)


def process(msg_id: str, event: dict, graph) -> None:
    try:
        kind = event.get("kind")
        if kind == "customer_reply":
            handle_customer_reply(event, graph)
        elif kind == "manager_decision":
            handle_manager_decision(event, graph)
        elif kind == "retry_action":
            handle_retry_action(event, graph)
        else:
            handle_shipping_event(event, graph)
            if PACE_SECONDS:
                time.sleep(PACE_SECONDS)        # spread token use across the minute
        event_queue.ack(msg_id)
        event_queue.clear_failures(msg_id)
    except Exception as err:
        attempts = event_queue.record_failure(msg_id)
        if attempts >= MAX_MESSAGE_ATTEMPTS:
            event_queue.dead_letter(msg_id, event, repr(err))
            print(f"[worker] {msg_id} failed {attempts} times -> moved to the dead-letter list: {err!r}")
        else:
            print(f"[worker] failed on {msg_id} (try {attempts}/{MAX_MESSAGE_ATTEMPTS}): {err!r}; "
                  f"retrying in about {RETRY_PENDING_SECONDS:.0f}s")


def main() -> None:
    event_queue.ensure_group()
    with PostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
        checkpointer.setup()                      # creates the checkpoint tables on first run
        graph = build_graph(checkpointer)
        print(f"[worker] {CONSUMER} waiting for events (Ctrl+C to stop)")
        for msg_id, event in event_queue.read(CONSUMER, pending=True):  # leftovers from a crash
            process(msg_id, event, graph)
        last_retry = time.monotonic()
        while True:
            for msg_id, event in event_queue.read(CONSUMER):
                process(msg_id, event, graph)
            if time.monotonic() - last_retry >= RETRY_PENDING_SECONDS:
                last_retry = time.monotonic()
                for msg_id, event in event_queue.read(CONSUMER, pending=True):  # failed earlier: try again
                    process(msg_id, event, graph)


if __name__ == "__main__":
    main()