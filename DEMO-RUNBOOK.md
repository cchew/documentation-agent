# Demo Runbook

## Before the demo

### 1. Activate venv and start FastAPI

```bash
cd repo
source .venv/bin/activate
uvicorn src.adapters.fastapi_app:app --reload --port 8000
```

### 2. Start ngrok (new terminal)

```bash
ngrok http --domain=flaxseed-vascular-cosmetics.ngrok-free.dev 8000
```

Slack webhook URL (already configured): `https://flaxseed-vascular-cosmetics.ngrok-free.dev/slack/actions`

### 3. Seed Confluence with pre-existing article

```bash
python demo/seed-confluence.py
```

### 4. Post demo Slack threads

```bash
python demo/post-threads.py
```

Posts Thread A → `#incidents`, Threads B & C → `#platform-eng`.

### 5. Run threads A, B, C through the shortcut (day before)

Trigger the ⚡ shortcut on all 3 threads so the Confluence space shows 3 existing articles before the live demo.

---

## During the demo

Use Thread A (incident) live in front of the audience. Threads B and C are backups.

---

## After the demo

### Reset Slack threads

```bash
python demo/reset-threads.py
```

### Reset Confluence (deletes all pages in KD space)

```bash
python demo/reset-confluence.py
```

### Reset storage backend

```bash
python demo/reset-storage.py    # clears storage backend (no-op for memory)
```

### Stop services

- `Ctrl+C` in the FastAPI terminal
- `Ctrl+C` in the ngrok terminal
