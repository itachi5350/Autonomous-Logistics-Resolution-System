from langchain_core.tools import tool

from app import policy


@tool
def check_inventory(sku: str) -> str:
    """Get current stock of a product, by SKU, in every warehouse."""
    stock = policy.stock_by_warehouse(sku)
    if not stock:
        return f"No inventory rows for SKU {sku}."
    per_wh = "; ".join(f"{wh}: {qty} units" for wh, qty in stock.items())
    return f"Stock for {sku} -> {per_wh}. Replacements can only ship from {policy.FULFILMENT_WAREHOUSE}."


@tool
def estimate_resolution_costs(order_id: int) -> str:
    """Get the cost in rupees of each resolution option (refund, replacement, cancel) for an order id."""
    c = policy.estimate_costs(order_id)
    return (f"Order {order_id}: refund = Rs {c['refund_inr']}, "
            f"replacement = Rs {c['replacement_inr']}, cancel = Rs {c['cancel_inr']}.")


TOOLS = [check_inventory, estimate_resolution_costs]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}