import json
import sys
import urllib.error
import urllib.request

API = "http://localhost:8000"


def main() -> None:
    if len(sys.argv) != 4:
        print('usage: python scripts/reply.py <case_id> <token> "your reply"')
        sys.exit(1)
    case_id, token, message = sys.argv[1:4]
    request = urllib.request.Request(
        f"{API}/cases/{case_id}/reply",
        data=json.dumps({"token": token, "message": message}).encode(),
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