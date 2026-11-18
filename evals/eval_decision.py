"""How does the Decision agent behave on real orders?  Run: python evals/eval_decision.py [repeats]
Runs the real nodes from the database lookup to the final decision (no customer email, no pause).
Single-option orders (TRK994) never reach the model in production, so they are left out."""
import json
import sys
import time
from collections import Counter, defaultdict

import common
from common import CACHE, DECISION_MODEL, pace, pct, percentile, save, wait
from langgraph.graph import END, START, StateGraph

from app import graph as g

REPEATS = int(sys.argv[1]) if len(sys.argv) > 1 else 2
CASES = ["TRK992", "TRK993", "TRK995", "TRK996"]


def build():
    b = StateGraph(g.CaseState)
    for name, fn in [("write_sql", g.write_sql), ("run_sql", g.run_sql), ("prepare", g.prepare),
                     ("agent", g.agent), ("tools", g.run_tools), ("recommend", g.recommend), ("verify", g.verify)]:
        b.add_node(name, fn)
    b.add_edge(START, "write_sql")
    b.add_edge("write_sql", "run_sql")
    b.add_conditional_edges("run_sql", g.route_after_run, {"prepare": "prepare", "write_sql": "write_sql", END: END})
    b.add_edge("prepare", "agent")
    b.add_conditional_edges("agent", g.should_continue, {"tools": "tools", "recommend": "recommend"})
    b.add_edge("tools", "agent")
    b.add_edge("recommend", "verify")
    b.add_edge("verify", END)
    return b.compile()


def main() -> None:
    app, delay = build(), pace(20)
    runs, cache = [], {}
    for rep in range(REPEATS):
        for tid in CASES:
            event = {"event_id": "eval", "tracking_id": tid, "event_type": "stuck_in_transit", "hours_stuck": 75}
            started = time.monotonic()
            try:
                final = app.invoke({"event": event}, {"recursion_limit": 30})
            except Exception as err:
                runs.append({"tracking_id": tid, "error": f"{type(err).__name__}: {str(err).splitlines()[0][:150]}"})
                print(f"[run {rep + 1}] {tid}: ERROR {runs[-1]['error']}")
                wait(delay)
                continue
            ms = int((time.monotonic() - started) * 1000)
            rec, decision = final.get("recommendation"), final.get("decision")
            if not rec or not decision:
                runs.append({"tracking_id": tid, "error": "no model recommendation (call failed)"})
                print(f"[run {rep + 1}] {tid}: ERROR no model recommendation")
                wait(delay)
                continue
            pick = rec["recommended_action"]
            tools = sum(1 for m in final.get("messages", []) if getattr(m, "type", "") == "tool")
            runs.append({"tracking_id": tid, "pick": pick, "offered": decision["offered_actions"],
                         "legal": pick in decision["offered_actions"], "overridden": decision["overridden"],
                         "tool_calls": tools, "ms": ms, "reasoning": rec["reasoning"]})
            cache[tid] = {"order": final["order"], "decision": decision}
            print(f"[run {rep + 1}] {tid}: offered={decision['offered_actions']} model picked {pick} "
                  f"(legal={pick in decision['offered_actions']}, tools={tools}, {ms} ms)")
            wait(delay)

    CACHE.mkdir(exist_ok=True)
    (CACHE / "cases.json").write_text(json.dumps(cache, indent=2, default=str), encoding="utf-8")

    ok = [r for r in runs if "error" not in r]
    picks = defaultdict(list)
    for r in ok:
        picks[r["tracking_id"]].append(r["pick"])
    consistent = sum(1 for v in picks.values() if len(set(v)) == 1)
    times = [r["ms"] for r in ok]
    print("\n=== Decision agent ===")
    print(f"model                       : {DECISION_MODEL}")
    print(f"runs / errors               : {len(runs)} / {len(runs) - len(ok)}  (errors excluded below)")
    print(f"model pick was LEGAL        : {pct(sum(r['legal'] for r in ok), len(ok))}")
    print(f"code had to override        : {pct(sum(r['overridden'] for r in ok), len(ok))}")
    print(f"used at least one tool      : {pct(sum(r['tool_calls'] > 0 for r in ok), len(ok))}")
    print(f"same pick on every repeat   : {consistent}/{len(picks)} orders")
    print(f"picks per order             : " + "; ".join(f"{k}: {dict(Counter(v))}" for k, v in picks.items()))
    print(f"investigation p50 / p95 ms  : {percentile(times, 50)} / {percentile(times, 95)}")
    print("note: there is no 'correct' answer key for which legal option is best, so this measures")
    print("legality, tool use and consistency, not business optimality.")

    save("decision", DECISION_MODEL, {
        "runs": len(runs), "errors": len(runs) - len(ok), "legal": f"{sum(r['legal'] for r in ok)}/{len(ok)}",
        "overridden": f"{sum(r['overridden'] for r in ok)}/{len(ok)}",
        "used_tools": f"{sum(r['tool_calls'] > 0 for r in ok)}/{len(ok)}",
        "consistent_orders": f"{consistent}/{len(picks)}", "p50_ms": percentile(times, 50),
        "p95_ms": percentile(times, 95)}, runs)


if __name__ == "__main__":
    main()