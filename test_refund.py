import json
import urllib.error
import urllib.request

BASE = "http://localhost:8001"


def call(method, path, body=None, key=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if key:
        req.add_header("Idempotency-Key", key)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


refund = {"order_id": 1, "amount_inr": 150000}
for attempt in range(1, 6):
    status, body = call("POST", "/refunds", refund, key="case-1:refund")
    print(f"attempt {attempt}: HTTP {status} {body}")

status, ledger = call("GET", "/_debug/ledger")
print("payouts that really happened:", ledger["count"])