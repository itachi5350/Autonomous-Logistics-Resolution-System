"""Numbers from the live database: cases, approvals, payouts, retries, duplicates.
Run: python evals/system_metrics.py"""
from collections import Counter

import common  # noqa: F401  (sets up the import path)
import httpx
import psycopg
from psycopg.rows import dict_row

from app.config import DATABASE_URL, MOCK_API_URL


def q(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


def main() -> None:
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        cases = q(conn, "SELECT status, count(*)::int AS n FROM cases GROUP BY status ORDER BY n DESC")
        approvals = q(conn, "SELECT approver, status, count(*)::int AS n FROM approvals GROUP BY approver, status")
        actions = q(conn, "SELECT idempotency_key, status, attempts FROM actions")
        calls = q(conn, "SELECT count(*)::int AS n, count(*) FILTER (WHERE NOT ok)::int AS failed, "
                        "count(*) FILTER (WHERE retries > 0)::int AS retried FROM agent_calls")[0]
    print("=== cases by status ===")
    for r in cases:
        print(f"  {r['status']:20} {r['n']}")
    print("\n=== approvals ===")
    for r in approvals:
        print(f"  {r['approver'] or '-':12} {r['status']:10} {r['n']}")

    done = [a for a in actions if a["status"] == "succeeded"]
    retried = [a for a in done if a["attempts"] > 1]
    print("\n=== provider actions ===")
    print(f"  total rows {len(actions)}, succeeded {len(done)}, other {len(actions) - len(done)}")
    print(f"  succeeded only after a retry: {len(retried)}   (max attempts seen: {max([a['attempts'] for a in actions] or [0])})")

    print("\n=== duplicate-payout check against the mock provider's ledger ===")
    try:
        ledger = httpx.get(f"{MOCK_API_URL}/_debug/ledger", timeout=3).json().get("payouts", [])
    except Exception:
        print("  mock provider is not running, so this check was skipped (start it on its port and rerun)")
        ledger = None
    if ledger is not None:
        seen = Counter(v for p in ledger for v in p.values() if isinstance(v, str))
        checked = [a for a in done if seen[a["idempotency_key"]] > 0]
        dupes = [a for a in checked if seen[a["idempotency_key"]] > 1]
        retried_checked = [a for a in checked if a["attempts"] > 1]
        print(f"  payouts in the current ledger: {len(ledger)}")
        print(f"  succeeded actions found in it: {len(checked)}, of which needed retries: {len(retried_checked)}")
        print(f"  keys paid MORE than once     : {len(dupes)}")
        print("  (the ledger forgets everything when the mock restarts, so older actions are not checked)")

    print("\n=== model calls recorded (all time, real cases only) ===")
    print(f"  calls {calls['n']}, failed {calls['failed']}, needed a retry {calls['retried']}")


if __name__ == "__main__":
    main()