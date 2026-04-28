# Demo Runbook

## Prerequisites

1. `.env` populated (copy from `.env.example`, fill real values)
2. ngrok running: `ngrok http 8000`
3. Slack app interactivity URL set to `https://<ngrok-host>/slack/actions`

## Run the server

```bash
source .venv/bin/activate
uvicorn src.adapters.fastapi_app:app --reload --port 8000
```

## Demo flow

1. In Slack, open a thread in a channel the bot is in
2. Click the ⚡ shortcut on the message
3. Select "Create KB Article"
4. Watch for the processing message (⏳), then the KB article card
5. Click "View in Confluence →" to verify the page

## Reset between runs

```bash
python demo/reset-threads.py       # removes seeded Slack threads
python demo/reset-confluence.py    # deletes all pages from the Confluence demo space
python demo/reset-storage.py       # clears storage backend (no-op for memory)
```

## Seed test data

```bash
python demo/post-threads.py        # posts sample threads to Slack
python demo/seed-confluence.py     # seeds Confluence with sample pages
```
