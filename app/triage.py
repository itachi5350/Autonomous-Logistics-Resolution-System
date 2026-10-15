from dataclasses import dataclass

from app.config import STUCK_HOURS_THRESHOLD
from app.models import ShippingEvent

ACTIONABLE_TYPES = {"stuck_in_transit", "delayed"}


@dataclass(frozen=True)
class Decision:
    open_case: bool
    reason: str


def triage(event: ShippingEvent) -> Decision:
    if event.event_type not in ACTIONABLE_TYPES:
        return Decision(False, f"event type '{event.event_type}' needs no action")
    if event.hours_stuck is None:
        return Decision(False, "stuck event without hours_stuck")
    if event.hours_stuck < STUCK_HOURS_THRESHOLD:
        return Decision(False, f"stuck only {event.hours_stuck}h (threshold {STUCK_HOURS_THRESHOLD}h)")
    return Decision(True, f"stuck {event.hours_stuck}h (threshold {STUCK_HOURS_THRESHOLD}h)")