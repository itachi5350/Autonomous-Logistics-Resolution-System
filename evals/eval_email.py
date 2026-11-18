"""Does the Communicator write emails that stick to the facts?  Run: python evals/eval_email.py [repeats]
Needs evals/cache/cases.json, which eval_decision.py writes."""
import json
import re
import sys

import common
from common import CACHE, COMMUNICATOR_MODEL, pace, pct, save, wait

from app import graph

REPEATS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
ACTION_WORDS = {"refund", "replacement", "cancel"}
CHECKS = ["product_named", "all_options_present", "no_invented_options", "no_invented_amounts",
          "suggestion_stated", "signed", "within_120_words"]
fallbacks = {"count": 0}
_original_fallback = graph.fallback_email


def counting_fallback(*args, **kwargs):
    fallbacks["count"] += 1
    return _original_fallback(*args, **kwargs)


graph.fallback_email = counting_fallback     # so we know when the model failed and the template was used


def norm(text: str) -> str:
    return re.sub(r"[\u2010-\u2015\u2212]", "-", text).replace("\u2019", "'").lower()


def numbers(text: str) -> set:
    return {int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", text) if n.replace(",", "").isdigit()
            and int(n.replace(",", "")) >= 100}


def check(order: dict, decision: dict, message: dict) -> dict:
    text = norm(message["subject"] + "\n" + message["body"])
    offered = set(decision["offered_actions"])
    given = " ".join(o["description"] for o in message["options"])
    allowed = numbers(given) | {order["amount_paid_inr"], order["order_value_inr"]}
    return {
        "product_named": norm(order["product_name"]) in text,
        "all_options_present": all(a in text for a in offered),
        "no_invented_options": not any(w in text for w in ACTION_WORDS - offered),
        "no_invented_amounts": numbers(text) <= allowed,
        "suggestion_stated": "suggest" in text or "recommend" in text,
        "signed": "customer care team" in text,
        "within_120_words": len(message["body"].split()) <= 120,
    }


def main() -> None:
    path = CACHE / "cases.json"
    if not path.exists():
        sys.exit("evals/cache/cases.json is missing. Run python evals/eval_decision.py first.")
    cases = json.loads(path.read_text(encoding="utf-8"))
    delay = pace(3)
    totals, rows, failures = {c: 0 for c in CHECKS}, [], []
    for rep in range(REPEATS):
        for tid, case in cases.items():
            before = fallbacks["count"]
            out = graph.compose_message({"order": case["order"], "decision": case["decision"], "clarify": False})
            message = out["customer_message"]
            used_template = fallbacks["count"] > before
            result = check(case["order"], case["decision"], message)
            for name, passed in result.items():
                totals[name] += passed
                if not passed:
                    failures.append((tid, name, message["subject"]))
            rows.append({"tracking_id": tid, "template": used_template, "checks": result,
                         "subject": message["subject"], "body": message["body"]})
            print(f"[run {rep + 1}] {tid}: " + ("TEMPLATE FALLBACK " if used_template else "")
                  + ("all checks passed" if all(result.values()) else "failed: " + ", ".join(k for k, v in result.items() if not v)))
            wait(delay)

    n = len(rows)
    clean = sum(all(r["checks"].values()) for r in rows)
    print("\n=== emails ===")
    print(f"model                : {COMMUNICATOR_MODEL}")
    print(f"emails generated     : {n}   (template fallbacks: {fallbacks['count']})")
    print(f"ALL checks passed    : {pct(clean, n)}")
    for name in CHECKS:
        print(f"  {name:22}: {pct(totals[name], n)}")
    for tid, name, subject in failures[:10]:
        print(f"  failed {name} on {tid}: {subject!r}")
    print("These are simple keyword and number checks. A failure may be a false alarm, so read the failing")
    print("emails in the saved JSON before drawing conclusions.")

    save("email", COMMUNICATOR_MODEL, {
        "emails": n, "all_checks": f"{clean}/{n}", "template_fallbacks": fallbacks["count"],
        **{c: f"{totals[c]}/{n}" for c in CHECKS}}, rows)


if __name__ == "__main__":
    main()