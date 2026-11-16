"""
  python scripts/dead_letters.py list              messages that failed too many times
  python scripts/dead_letters.py requeue <id>      put one back on the queue
  python scripts/dead_letters.py poison            send a deliberately broken message (for the demo)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import event_queue  # noqa: E402


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "list":
        entries = event_queue.list_dead_letters()
        if not entries:
            print("the dead-letter list is empty")
        for dead_id, fields in entries:
            print(f"{dead_id}   original message {fields.get('original_id')}")
            print(f"   event: {fields.get('event')}")
            print(f"   error: {fields.get('error')}")
    elif command == "requeue" and len(sys.argv) == 3:
        print("requeued" if event_queue.requeue_dead_letter(sys.argv[2]) else "no such dead letter")
    elif command == "poison":
        event_queue.publish({"kind": "customer_reply", "note": "deliberately broken: no case_id"})
        print("sent a broken message: watch the worker retry it and then dead-letter it")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()