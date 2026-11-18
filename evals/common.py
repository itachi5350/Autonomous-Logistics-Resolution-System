"""Shared helpers for the evaluation scripts."""
import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))          # so "from app import ..." works
RESULTS = HERE / "results"
CACHE = HERE / "cache"

from app import observability  # noqa: E402
from app.config import COMMUNICATOR_MODEL, DECISION_MODEL, GROQ_MODEL  # noqa: E402

# Evaluation calls must not pollute the real call statistics shown on the dashboard.
observability.log_call = lambda *args, **kwargs: None


def models() -> dict:
    return {"db_agent": GROQ_MODEL, "decision_agent": DECISION_MODEL, "communicator": COMMUNICATOR_MODEL}


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "0/0"


def percentile(values: list, p: float):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(p / 100 * len(ordered)) - 1)]


def wait(seconds: float) -> None:
    """Pause between model calls so the free tier's tokens-per-minute limit is not hit."""
    if seconds > 0:
        time.sleep(seconds)


def pace(default: float) -> float:
    return float(os.getenv("EVAL_PACE", str(default)))


def save(name: str, model: str, headline: dict, details: list) -> Path:
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = RESULTS / f"{name}-{stamp}.json"
    path.write_text(json.dumps({"name": name, "model": model, "when": stamp, "headline": headline,
                                "details": details}, indent=2, default=str), encoding="utf-8")
    print(f"\nsaved: {path}")
    return path