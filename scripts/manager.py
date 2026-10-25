import json
import sys
import urllib.error
import urllib.request

API = "http://localhost:8000"


def main() -> None:
    if len(sys.argv) < 4 or sys.argv[3] not in ("approve", "reject"):
        print('usage: python scripts/manager.py <case_id> <token> approve|reject ["note"]')
        sys.exit(1)
    case_id, token, verdict = sys.argv[1:4]
    note = sys.argv[4] if len(sys.argv) > 4 else ""
    body = {"token": token, "approved": verdict == "approve", "approver": "manager", "note": note}
    request = urllib.request.Request(
        f"{API}/manager/cases/{case_id}/decision",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            print(response.status, response.read().decode())
    except urllib.error.HTTPError as err:
        print(err.code, err.read().decode())


if __name__ == "__main__":
    main()