from pydantic import BaseModel, Field


class ShippingEvent(BaseModel):
    event_id: str = Field(min_length=1)
    tracking_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    hours_stuck: int | None = Field(default=None, ge=0)