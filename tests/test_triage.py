from app.models import ShippingEvent
from app.triage import triage


def ev(event_type, hours=None):
    return ShippingEvent(event_id="e1", tracking_id="TRK1", event_type=event_type, hours_stuck=hours)


def test_healthy_event_is_ignored():
    assert triage(ev("arrived_at_hub")).open_case is False


def test_exactly_72_hours_opens_a_case():
    assert triage(ev("stuck_in_transit", 72)).open_case is True


def test_71_hours_is_ignored():
    assert triage(ev("stuck_in_transit", 71)).open_case is False


def test_stuck_without_hours_is_ignored():
    assert triage(ev("stuck_in_transit")).open_case is False