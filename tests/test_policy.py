from app.policy import customer_options, offered_actions, resolve_recommendation


def test_prepaid_in_stock_offers_refund_then_replacement():
    assert offered_actions("PREPAID", True) == ["refund", "replacement"]


def test_prepaid_out_of_stock_offers_only_refund():
    assert offered_actions("PREPAID", False) == ["refund"]


def test_cod_never_offers_refund():
    assert "refund" not in offered_actions("COD", True)
    assert "refund" not in offered_actions("COD", False)


def test_cod_offers_cancel_and_replacement_when_in_stock():
    assert offered_actions("COD", True) == ["cancel", "replacement"]


def test_legal_recommendation_is_kept():
    assert resolve_recommendation("replacement", ["refund", "replacement"]) == ("replacement", False)


def test_illegal_recommendation_is_overridden_to_safest_option():
    assert resolve_recommendation("refund", ["cancel", "replacement"]) == ("cancel", True)


def test_missing_recommendation_falls_back():
    assert resolve_recommendation(None, ["refund"]) == ("refund", True)

def test_customer_options_only_describe_offered_actions():
    options = customer_options({"amount_paid_inr": 8999}, ["refund"])
    assert [o["action"] for o in options] == ["refund"]
    assert "8,999" in options[0]["description"]