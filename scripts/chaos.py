"""Change the mock's failure behaviour WITHOUT restarting it (a restart makes it forget every key).

  python scripts/chaos.py 0 0      healthy: nothing fails
  python scripts/chaos.py 0.2 0    normal: 20% of calls fail with a 503 before doing anything
  python scripts/chaos.py 1 1      lost response: every call is recorded, then answered with a 503
  python scripts/chaos.py 1 0      always down: every call fails before doing anything
  python scripts/chaos.py show     print the current settings
"""
import json
import sys
import urllib.request

URL = "http://localhost:8001/_debug/chaos"


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "show":
        with urllib.request.urlopen(URL) as response:
            print(response.read().decode())
        return
    rate = float(sys.argv[1])
    after_commit = len(sys.argv) > 2 and sys.argv[2] == "1"
    request = urllib.request.Request(
        URL,
        data=json.dumps({"rate": rate, "after_commit": after_commit}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        print("mock is now:", response.read().decode())


if __name__ == "__main__":
    main()