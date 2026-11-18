"""One line per saved evaluation run.  Run: python evals/summary.py"""
import json

from common import RESULTS


def main() -> None:
    files = sorted(RESULTS.glob("*.json")) if RESULTS.exists() else []
    if not files:
        print("no saved results yet")
        return
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        print(f"{d['name']:10} {d['when']}  {d['model']}")
        print("   " + ", ".join(f"{k}={v}" for k, v in d["headline"].items()))


if __name__ == "__main__":
    main()