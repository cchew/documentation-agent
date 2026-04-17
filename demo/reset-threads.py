"""
Delete all demo Slack threads posted by post-threads.py.

Usage:
    python demo/reset-threads.py

Reads demo/.demo_state.json and deletes every message recorded there.
Run this to reset the demo workspace to a clean state.
"""
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

STATE_FILE = Path(__file__).parent / ".demo_state.json"


def main() -> None:
    if not STATE_FILE.exists():
        print("No state file found — nothing to delete.")
        print(f"Expected: {STATE_FILE}")
        return

    state = json.loads(STATE_FILE.read_text())
    client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
    total_deleted = 0
    total_failed = 0

    for filename, info in state.items():
        channel_id = info["channel_id"]
        timestamps = info["timestamps"]
        print(f"\nDeleting {filename} ({len(timestamps)} messages from #{info['channel_name']})")

        # Delete in reverse order (replies before parent)
        for ts in reversed(timestamps):
            try:
                client.chat_delete(channel=channel_id, ts=ts)
                total_deleted += 1
                time.sleep(0.3)
            except SlackApiError as e:
                error = e.response["error"]
                if error == "message_not_found":
                    print(f"  Skipped {ts} (already deleted)")
                else:
                    print(f"  Failed to delete {ts}: {error}")
                    total_failed += 1

    STATE_FILE.unlink()
    print(f"\nDone. Deleted {total_deleted} messages, {total_failed} failed.")
    print("State file removed — run post-threads.py to re-post.")


if __name__ == "__main__":
    main()
