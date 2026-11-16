import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from app.config import DATABASE_URL  # noqa: E402

QUERY = """
SELECT c.id, c.status, c.customer_choice, c.action_amount_inr, c.note,
       a.status AS action_status, a.attempts, a.last_error
FROM cases c LEFT JOIN actions a ON a.case_id = c.id
WHERE c.status IN ('failed_needs_human', 'rejected')
ORDER BY c.created_at DESC
"""


def main() -> None:
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        rows = conn.execute(QUERY).fetchall()
    if not rows:
        print("nothing needs a human right now")
        return
    for row in rows:
        amount = f"Rs {row['action_amount_inr']:,}" if row["action_amount_inr"] is not None else "-"
        print(f"{row['id']}   {row['status']}   {row['customer_choice'] or '-'}   {amount}")
        print(f"   why : {row['note'] or row['last_error'] or 'no reason recorded'}")
        if row["status"] == "failed_needs_human" and row["action_status"] in ("failed", "pending"):
            print(f"   next: python scripts/retry_action.py {row['id']}   (safe: same idempotency key)")
        elif row["status"] == "rejected":
            print("   next: nothing was paid. Follow up with the customer or the manager.")
        else:
            print("   next: look at the case by hand.")
        print()


if __name__ == "__main__":
    main()