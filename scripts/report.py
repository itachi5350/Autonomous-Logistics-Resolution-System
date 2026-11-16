"""
  python scripts/report.py              model-call stats for the last 24 hours
  python scripts/report.py 2            ... for the last 2 hours
  python scripts/report.py case <id>    every model call for one case, in order
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from app.config import DATABASE_URL  # noqa: E402

STATS = """
SELECT agent, step, model,
       COUNT(*)                                             AS calls,
       COUNT(*) FILTER (WHERE NOT ok)                       AS failed,
       COUNT(*) FILTER (WHERE retries > 0)                  AS retried,
       AVG(latency_ms)                                      AS avg_ms,
       percentile_cont(0.5)  WITHIN GROUP (ORDER BY latency_ms) AS p50_ms,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_ms
FROM agent_calls
WHERE created_at > now() - (%s * interval '1 hour')
GROUP BY agent, step, model
ORDER BY agent, step
"""

CASE_CALLS = """
SELECT created_at, agent, step, ok, retries, latency_ms, error
FROM agent_calls WHERE case_id = %s ORDER BY id
"""


def show_stats(hours: float) -> None:
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        rows = conn.execute(STATS, (hours,)).fetchall()
    if not rows:
        print("no model calls recorded in that window")
        return
    print(f"model calls in the last {hours:g} hour(s)")
    print(f"{'agent':<16}{'step':<17}{'model':<22}{'calls':>6}{'failed':>8}{'retried':>9}"
          f"{'avg ms':>9}{'p50 ms':>9}{'p95 ms':>9}")
    for r in rows:
        print(f"{r['agent']:<16}{r['step']:<17}{r['model'][:20]:<22}{r['calls']:>6}{r['failed']:>8}"
              f"{r['retried']:>9}{round(r['avg_ms']):>9}{round(r['p50_ms']):>9}{round(r['p95_ms']):>9}")
    print("\nnote: with few calls, p95 is close to the slowest call. Treat it as a hint, not a measurement.")


def show_case(case_id: str) -> None:
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        rows = conn.execute(CASE_CALLS, (case_id,)).fetchall()
    if not rows:
        print(f"no model calls recorded for {case_id}")
        return
    print(f"model calls for {case_id}")
    for r in rows:
        status = "ok" if r["ok"] else "FAILED"
        retry = f", {r['retries']} retry(ies)" if r["retries"] else ""
        print(f"  {r['created_at']:%H:%M:%S}  {r['agent']:<16}{r['step']:<17}{status:<7}{r['latency_ms']:>6} ms{retry}")
        if r["error"]:
            print(f"      error: {r['error']}")


def main() -> None:
    args = sys.argv[1:]
    if args[:1] == ["case"] and len(args) == 2:
        show_case(args[1])
    elif not args:
        show_stats(24)
    elif len(args) == 1:
        show_stats(float(args[0]))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()