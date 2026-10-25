"""Plain-code business rules. No LLM in this file, so it is easy to test."""
import psycopg
from psycopg.rows import dict_row

from app.config import FULFILMENT_WAREHOUSE, READONLY_DATABASE_URL, REPLACEMENT_SHIPPING_INR


def _fetch(sql: str, params: tuple) -> list[dict]:
    with psycopg.connect(READONLY_DATABASE_URL, row_factory=dict_row) as conn:
        return conn.execute(sql, params).fetchall()


def stock_by_warehouse(sku: str) -> dict[str, int]:
    rows = _fetch("SELECT warehouse, quantity FROM inventory WHERE sku = %s ORDER BY warehouse", (sku,))
    return {r["warehouse"]: r["quantity"] for r in rows}


def stock_at_fulfilment(sku: str) -> int:
    return stock_by_warehouse(sku).get(FULFILMENT_WAREHOUSE, 0)


def estimate_costs(order_id: int) -> dict:
    rows = _fetch(
        "SELECT o.amount_paid_inr, p.price_inr FROM orders o JOIN products p ON p.sku = o.sku WHERE o.id = %s",
        (order_id,),
    )
    if not rows:
        raise ValueError(f"order {order_id} not found")
    return {
        "refund_inr": rows[0]["amount_paid_inr"],
        "replacement_inr": rows[0]["price_inr"] + REPLACEMENT_SHIPPING_INR,
        "cancel_inr": 0,
    }


def offered_actions(payment_method: str, replacement_in_stock: bool) -> list[str]:
    """The conservative option comes first. COD can never be refunded: no money was collected."""
    actions = ["refund"] if payment_method == "PREPAID" else ["cancel"]
    if replacement_in_stock:
        actions.append("replacement")
    return actions


def resolve_recommendation(recommended: str | None, offered: list[str]) -> tuple[str, bool]:
    """Returns (final_action, was_overridden). An illegal or missing pick falls back to the safest option."""
    if recommended in offered:
        return recommended, False
    return offered[0], True

def customer_options(order: dict, offered: list[str]) -> list[dict]:
    """Plain-language text for each legal option. Code writes this, not the model."""
    texts = {
        "refund": f"A full refund of Rs {order['amount_paid_inr']:,} to your original payment method",
        "replacement": f"A free replacement, shipped from our {FULFILMENT_WAREHOUSE} warehouse",
        "cancel": "Cancel the order. You will not be charged anything",
    }
    return [{"action": a, "description": texts[a]} for a in offered]