"""
Slack API helpers: signature verification, thread fetching, response posting.
"""
import hashlib
import hmac
import os
import time

import httpx
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


def verify_signature(body: bytes, timestamp: str, signature: str) -> bool:
    """
    Verify Slack request signature using HMAC-SHA256.
    Returns False if the timestamp is stale (> 5 minutes) or the signature doesn't match.
    """
    signing_secret = os.environ["SLACK_SIGNING_SECRET"]

    if abs(time.time() - float(timestamp)) > 300:
        return False

    base = f"v0:{timestamp}:{body.decode('utf-8')}"
    expected = "v0=" + hmac.new(
        signing_secret.encode("utf-8"),
        base.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


def fetch_thread(channel_id: str, thread_ts: str) -> str:
    """
    Fetch all messages in a Slack thread and return them as formatted text.
    Format: [HH:MM] <@UXXXXXXX>: message
    """
    client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
    try:
        response = client.conversations_replies(channel=channel_id, ts=thread_ts)
    except SlackApiError as e:
        raise RuntimeError(f"Failed to fetch thread: {e.response['error']}") from e

    messages = response.get("messages", [])
    lines = []
    for msg in messages:
        ts = float(msg.get("ts", 0))
        t = time.strftime("%H:%M", time.localtime(ts))
        user = msg.get("user", "unknown")
        text = msg.get("text", "")
        lines.append(f"[{t}] <@{user}>: {text}")

    return "\n".join(lines)


def post_processing(channel_id: str, thread_ts: str) -> str:
    """Post an 'in progress' message and return its ts for later update."""
    client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
    try:
        result = client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="⏳ Generating KB article...",
        )
        return result["ts"]
    except SlackApiError as e:
        raise RuntimeError(f"Failed to post processing message: {e.response['error']}") from e


def update_response(channel_id: str, message_ts: str, payload: dict) -> None:
    """Update the in-progress message with the final result."""
    client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
    try:
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            blocks=payload["blocks"],
            text="KB Article result",
        )
    except SlackApiError as e:
        raise RuntimeError(f"Failed to update Slack message: {e.response['error']}") from e


def post_response(channel_id: str, thread_ts: str, payload: dict) -> None:
    """Post a Block Kit message back into the originating thread."""
    client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
    try:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            blocks=payload["blocks"],
            text="KB Article result",  # fallback for notifications
        )
    except SlackApiError as e:
        raise RuntimeError(f"Failed to post Slack response: {e.response['error']}") from e
