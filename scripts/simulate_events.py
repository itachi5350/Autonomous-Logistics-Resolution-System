import json
import time
import urllib.error
import urllib.request

URL = "http://localhost:8000/webhook/shipping-update"
run = int(time.time())  # makes event ids unique on every run


def send(label, event):
    req = urllib.request.Request(
        URL, data=json.dumps(event).encode(), method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"{label:<28} -> {resp.status} {resp.read().decode()}")
    except urllib.error.HTTPError as err:
        print(f"{label:<28} -> {err.code} {err.read().decode()}")


def evt(n, tracking_id, event_type, hours=None):
    e = {"event_id": f"evt-{run}-{n}", "tracking_id": tracking_id, "event_type": event_type}
    if hours is not None:
        e["hours_stuck"] = hours
    return e


send("healthy package at hub", evt(1, "TRK991", "arrived_at_hub"))
send("MacBook stuck 73h", evt(2, "TRK992", "stuck_in_transit", 73))
send("mouse stuck 75h", evt(3, "TRK993", "stuck_in_transit", 75))
send("MacBook event sent AGAIN", evt(2, "TRK992", "stuck_in_transit", 73))
send("headphones stuck only 40h", evt(4, "TRK994", "stuck_in_transit", 40))
send("COD mouse stuck 76h", evt(5, "TRK995", "stuck_in_transit", 76))
send("COD MacBook stuck 77h", evt(6, "TRK996", "stuck_in_transit", 77))
send("Prepaid headphones stuck 80h (no Bengaluru stock)", evt(7, "TRK994", "stuck_in_transit", 80))