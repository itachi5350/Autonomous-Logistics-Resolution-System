import httpx

from app.actions import _is_transient, idempotency_key


def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://mock/refunds")
    return httpx.HTTPStatusError("boom", request=request, response=httpx.Response(code, request=request))


def test_server_side_errors_are_retried():
    for code in (429, 502, 503, 504):
        assert _is_transient(_status_error(code))


def test_client_errors_are_never_retried():
    for code in (400, 404, 409, 422):
        assert not _is_transient(_status_error(code))


def test_network_errors_are_retried():
    assert _is_transient(httpx.ConnectError("refused"))
    assert _is_transient(httpx.ReadTimeout("too slow"))


def test_unknown_errors_are_not_retried():
    assert not _is_transient(ValueError("bug"))


def test_idempotency_key_is_stable_and_scoped_per_action():
    assert idempotency_key("case-1", "refund") == idempotency_key("case-1", "refund")
    assert idempotency_key("case-1", "refund") != idempotency_key("case-1", "cancel")