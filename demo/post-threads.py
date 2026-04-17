"""
Post demo Slack threads before the talk.

Usage:
    python demo/post-threads.py

Posts Thread A to #incidents, Threads B and C to #platform-eng.
Saves posted message timestamps to demo/.demo_state.json for use by reset-threads.py.
"""
import json
import os
import re
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
THREADS_DIR = Path(__file__).parent / "threads"

THREAD_CONFIG = [
    ("thread-a-incident.md", "incidents"),
    ("thread-b-qa.md",       "platform-eng"),
    ("thread-c-howto.md",    "platform-eng"),
]

MESSAGE_RE = re.compile(r"^\[(\d{2}:\d{2})\] @([\w.]+): (.+)$")


def parse_thread(filepath: Path) -> list[str]:
    messages = []
    for line in filepath.read_text().splitlines():
        m = MESSAGE_RE.match(line.strip())
        if m:
            user, text = m.group(2), m.group(3)
            messages.append(f"*{user}:* {text}")
    return messages


def ensure_channel(client: WebClient, name: str) -> str:
    """Return channel ID, creating the channel if it doesn't exist."""
    try:
        result = client.conversations_create(name=name, is_private=False)
        channel_id = result["channel"]["id"]
        print(f"  Created #{name} ({channel_id})")
    except SlackApiError as e:
        if e.response["error"] == "name_taken":
            result = client.conversations_list(types="public_channel", limit=200)
            for ch in result["channels"]:
                if ch["name"] == name:
                    channel_id = ch["id"]
                    print(f"  Found existing #{name} ({channel_id})")
                    break
            else:
                raise RuntimeError(f"Channel #{name} exists but couldn't be found in list") from e
        else:
            raise

    # Ensure bot is a member
    try:
        client.conversations_join(channel=channel_id)
    except SlackApiError:
        pass  # Already a member

    return channel_id


def post_thread(client: WebClient, channel_id: str, messages: list[str]) -> list[str]:
    """Post messages as a thread. Returns list of message timestamps."""
    timestamps = []
    thread_ts = None

    for i, text in enumerate(messages):
        kwargs = {"channel": channel_id, "text": text, "unfurl_links": False}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts

        result = client.chat_postMessage(**kwargs)
        ts = result["ts"]
        timestamps.append(ts)

        if i == 0:
            thread_ts = ts

        time.sleep(0.5)  # Slack rate limit: ~1 req/sec on free tier

    return timestamps


def main() -> None:
    client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
    state: dict[str, dict] = {}

    for filename, channel_name in THREAD_CONFIG:
        filepath = THREADS_DIR / filename
        print(f"\nPosting {filename} → #{channel_name}")

        messages = parse_thread(filepath)
        print(f"  Parsed {len(messages)} messages")

        channel_id = ensure_channel(client, channel_name)
        timestamps = post_thread(client, channel_id, messages)

        state[filename] = {
            "channel_id": channel_id,
            "channel_name": channel_name,
            "timestamps": timestamps,
        }
        print(f"  Posted {len(timestamps)} messages (thread_ts={timestamps[0]})")

    STATE_FILE.write_text(json.dumps(state, indent=2))
    print(f"\nState saved to {STATE_FILE}")
    print("\nDone. All threads posted.")


if __name__ == "__main__":
    main()
