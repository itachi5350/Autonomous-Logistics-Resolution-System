from typing import Literal

from pydantic import BaseModel, Field


class ShippingEvent(BaseModel):
    event_id: str = Field(min_length=1)
    tracking_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")  # strict on purpose: it ends up in an LLM prompt
    event_type: str = Field(min_length=1)
    hours_stuck: int | None = Field(default=None, ge=0)


class SqlQuery(BaseModel):
    """What the LLM must return."""
    sql: str = Field(description="One read-only PostgreSQL SELECT statement")


class OrderInfo(BaseModel):
    """What the query result must look like before we trust it."""
    tracking_id: str
    order_id: int
    customer_name: str
    customer_email: str
    sku: str
    product_name: str
    order_value_inr: int
    amount_paid_inr: int
    payment_method: Literal["PREPAID", "COD"]
    shipment_status: str

class Recommendation(BaseModel):
    recommended_action: Literal["refund", "replacement", "cancel"]
    reasoning: str