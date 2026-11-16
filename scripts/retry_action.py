import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402

from app import event_queue  # noqa: E402
from app.config import DATABASE_URL  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python scripts/retry_action.py <case_id>")
        sys.exit(1)
    case_id = sys.argv[1]
    with psycopg.connect(DATABASE_URL) as conn:
        row = conn.execute("SELECT status FROM cases WHERE id = %s", (case_id,)).fetchone()
    if row is None:
        print(f"no such case: {case_id}")
        sys.exit(1)
    if row[0] != "failed_needs_human":
        print(f"case is '{row[0]}', not 'failed_needs_human': nothing to retry")
        sys.exit(1)
    event_queue.publish({"kind": "retry_action", "case_id": case_id})
    print("queued: the worker will re-run the action with the SAME idempotency key (safe: it cannot pay twice)")


if __name__ == "__main__":
    main()