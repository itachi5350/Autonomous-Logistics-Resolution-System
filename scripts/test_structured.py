"""A/B test: how often does each structured-output method fail? Makes real model calls."""
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_groq import ChatGroq  # noqa: E402

from app.config import COMMUNICATOR_MODEL  # noqa: E402  (also loads .env)
from app.graph import COMPOSE_PROMPT  # noqa: E402
from app.models import CustomerEmail  # noqa: E402

FACTS = (
    "Customer name: Diya Nair\nProduct: Wireless Mouse\nOptions:\n"
    "- refund: A full refund of Rs 1,499 to your original payment method\n"
    "- replacement: A free replacement, shipped from our Bengaluru warehouse\n"
    "Suggested option: replacement"
)
RUNS = 8
PAUSE = 6   # seconds between calls, to stay under the tokens-per-minute limit


def trial(method: str | None) -> tuple[int, Counter]:
    llm = ChatGroq(model=COMMUNICATOR_MODEL, temperature=0.2)
    chain = llm.with_structured_output(CustomerEmail, method=method) if method else llm.with_structured_output(CustomerEmail)
    ok, errors = 0, Counter()
    for _ in range(RUNS):
        try:
            chain.invoke([("system", COMPOSE_PROMPT), ("human", FACTS)])
            ok += 1
        except Exception as err:
            errors[f"{type(err).__name__}: {str(err)[:110]}"] += 1
        time.sleep(PAUSE)
    return ok, errors


for method in (None, "json_schema"):
    ok, errors = trial(method)
    print(f"method={method or 'default (function_calling)'}: {ok}/{RUNS} succeeded")
    for message, count in errors.items():
        print(f"    {count}x {message}")