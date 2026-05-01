"""
End-to-end pipeline test:
  signed POST /slack/actions  ->  FastAPI  ->  Claude API  ->  Confluence page

Prereqs (run from repo/ with venv active):
  - uvicorn src.adapters.fastapi_app:app --port 8000  (running)
  - .env populated (SLACK_SIGNING_SECRET, API_KEY, CONFLUENCE_URL, CONFLUENCE_SPACE_KEY, ...)
  - playwright-cli on PATH (for Confluence UI assertion)

Usage:
  python tests/e2e_pipeline.py
  python tests/e2e_pipeline.py --base-url http://localhost:8000 --skip-ui

First UI run will pause for manual Atlassian login, then save state to
tests/.playwright-state.json so subsequent runs skip auth.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

DEMO_DIR = ROOT / "demo"
STATE_FILE = DEMO_DIR / ".demo_state.json"
PW_STATE = ROOT / "tests" / ".playwright-state.json"
PW_SESSION = "doco-e2e"
THREAD_KEY = "thread-a-incident.md"  # Thread A → #incidents


def seed_threads() -> dict:
    """Run post-threads.py and return state for THREAD_KEY."""
    print("[1/5] Seeding Slack threads...")
    subprocess.run(
        [sys.executable, str(DEMO_DIR / "post-threads.py")],
        check=True,
        cwd=ROOT,
    )
    state = json.loads(STATE_FILE.read_text())
    if THREAD_KEY not in state:
        raise RuntimeError(f"{THREAD_KEY} missing from {STATE_FILE}")
    entry = state[THREAD_KEY]
    print(f"      channel_id={entry['channel_id']}  thread_ts={entry['timestamps'][0]}")
    return entry


def build_signed_request(channel_id: str, thread_ts: str) -> tuple[str, dict]:
    """Build a form-encoded message_action payload + Slack-signed headers."""
    secret = os.environ["SLACK_SIGNING_SECRET"]
    payload = {
        "type": "message_action",
        "callback_id": "create_kb_article",
        "channel": {"id": channel_id, "name": "incidents"},
        "message": {"ts": thread_ts, "text": "demo"},
        "user": {"id": "UE2ETEST"},
        "team": {"id": "TE2ETEST"},
    }
    body = "payload=" + urllib.parse.quote(json.dumps(payload))
    timestamp = str(int(time.time()))
    base = f"v0:{timestamp}:{body}".encode()
    sig = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": sig,
    }
    return body, headers


def fire_request(base_url: str, body: str, headers: dict) -> None:
    print("[2/5] POST /slack/actions (signed)...")
    r = httpx.post(f"{base_url}/slack/actions", content=body, headers=headers, timeout=10)
    if r.status_code != 200:
        raise RuntimeError(f"/slack/actions returned {r.status_code}: {r.text}")


def poll_articles(base_url: str, article_id: str, timeout: int = 30) -> dict:
    print(f"[3/5] Polling GET /articles for {article_id} (timeout={timeout}s)...")
    api_key = os.environ["API_KEY"]
    headers = {"X-API-Key": api_key}
    deadline = time.time() + timeout
    last_count = -1
    while time.time() < deadline:
        r = httpx.get(f"{base_url}/articles", headers=headers, timeout=10)
        r.raise_for_status()
        articles = r.json()
        if len(articles) != last_count:
            print(f"      {len(articles)} article(s) in store")
            last_count = len(articles)
        for a in articles:
            if a.get("id") == article_id:
                if not a.get("extraction_viable", True):
                    raise RuntimeError(f"Extraction not viable: {a.get('low_confidence_reason')}")
                print(f"      Found: {a['title']!r}")
                return a
        time.sleep(2)
    raise TimeoutError(f"Article {article_id} did not appear within {timeout}s")


def assert_confluence_ui(article: dict, skip: bool) -> None:
    if skip:
        print("[4/5] Skipping Confluence UI assertion (--skip-ui)")
        return
    if not shutil.which("playwright-cli"):
        print("[4/5] playwright-cli not on PATH — skipping UI assertion")
        return

    base = os.environ["CONFLUENCE_URL"].rstrip("/")
    space = os.environ["CONFLUENCE_SPACE_KEY"]
    space_url = f"{base}/spaces/{space}"
    title = article["title"]
    summary = article["summary"]

    print(f"[4/5] Confluence UI assertion: space={space} title={title!r}")

    def pw(*args: str, raw: bool = False) -> subprocess.CompletedProcess:
        cmd = ["playwright-cli", "-s", PW_SESSION]
        if raw:
            cmd.append("--raw")
        cmd.extend(args)
        return subprocess.run(cmd, check=False, capture_output=True, text=True)

    # Reuse saved auth state if present.
    if PW_STATE.exists():
        pw("open", "--persistent")
        pw("state-load", str(PW_STATE))
    else:
        pw("open", "--persistent")

    pw("goto", space_url)

    # If login is required (no saved state), pause for manual sign-in.
    if not PW_STATE.exists():
        input(
            "\n      Sign in to Atlassian in the opened browser, navigate to the space, "
            "then press Enter to continue..."
        )
        pw("state-save", str(PW_STATE))
        print(f"      Saved auth state to {PW_STATE}")

    # Search the space for the article title.
    snap = pw("--raw", "snapshot", raw=True).stdout
    if title not in snap:
        # Fallback: search via URL
        search_url = f"{base}/search?text={urllib.parse.quote(title)}&spaces={space}"
        pw("goto", search_url)
        snap = pw("--raw", "snapshot", raw=True).stdout

    summary_first = summary.split(".")[0].strip()[:60]
    missing = []
    if title not in snap:
        missing.append(f"title {title!r}")
    if summary_first and summary_first not in snap:
        # Title alone is a sufficient signal; summary is best-effort.
        print(f"      (summary fragment {summary_first!r} not visible in current view)")

    pw("close")

    if missing:
        raise AssertionError(f"Confluence UI missing: {', '.join(missing)}")
    print("      UI assertion passed.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("E2E_BASE_URL", "http://localhost:8000"))
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--skip-ui", action="store_true")
    args = ap.parse_args()

    for var in ("SLACK_SIGNING_SECRET", "API_KEY", "CONFLUENCE_URL", "CONFLUENCE_SPACE_KEY"):
        if not os.environ.get(var):
            raise SystemExit(f"Missing env var: {var}")

    entry = seed_threads()
    channel_id = entry["channel_id"]
    thread_ts = entry["timestamps"][0]
    article_id = f"{channel_id}_{thread_ts}"

    body, headers = build_signed_request(channel_id, thread_ts)
    fire_request(args.base_url, body, headers)
    article = poll_articles(args.base_url, article_id, timeout=args.timeout)
    assert_confluence_ui(article, skip=args.skip_ui)

    print("[5/5] E2E PASS")


if __name__ == "__main__":
    main()
