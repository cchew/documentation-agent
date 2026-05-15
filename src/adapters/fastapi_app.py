"""
Documentation Agent — FastAPI backend.

Endpoints:
  POST /slack/actions  — Slack message shortcut webhook
  POST /extract        — Direct extraction (testing / Notion path)
  GET  /articles       — List all saved articles
"""
import json
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from src.extraction.extractor import extract
from src.hitl_store import consume as hitl_consume
from src.pipeline import run_pipeline
from src.slack_client import post_processing, post_response, update_response, verify_signature
from src.storage import get_store
from src.update_or_create import execute_cancel, execute_create, execute_update

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast at startup if required env vars are missing.
    required = ["ANTHROPIC_API_KEY", "SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")
    yield


app = FastAPI(title="Documentation Agent", lifespan=lifespan)

_api_key_header = APIKeyHeader(name="X-API-Key")


def _require_api_key(key: str = Depends(_api_key_header)) -> None:
    expected = os.environ.get("API_KEY")
    if not expected or key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/slack/actions")
async def slack_actions(request: Request, background_tasks: BackgroundTasks) -> Response:
    """
    Receives Slack message shortcut payloads.
    Must return HTTP 200 within 3 seconds — extraction runs in the background.
    """
    body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not verify_signature(body, timestamp, signature):
        logger.warning("Invalid Slack signature from %s", request.client.host if request.client else "unknown")
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    form = await request.form()
    if "payload" not in form:
        raise HTTPException(status_code=400, detail="Missing payload")
    try:
        payload = json.loads(form["payload"])
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid payload JSON")

    if payload.get("type") != "message_action":
        return Response(status_code=200)

    try:
        channel_id: str = payload["channel"]["id"]
        thread_ts: str = payload["message"]["ts"]
        user_id: str = payload["user"]["id"]
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Missing field in payload: {e}") from e

    processing_ts = post_processing(channel_id, thread_ts)
    background_tasks.add_task(run_pipeline, channel_id, thread_ts, processing_ts, user_id)
    return Response(status_code=200)


@app.post("/slack/interactions")
async def slack_interactions(request: Request, background_tasks: BackgroundTasks) -> Response:
    """
    Receives Slack Block Kit interactive component payloads (button clicks).
    Must return HTTP 200 within 3 seconds — routing runs in the background.
    Returns a JSON body that Slack uses to update the original message immediately.
    """
    body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not verify_signature(body, timestamp, signature):
        logger.warning("Invalid Slack signature on /slack/interactions")
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    form = await request.form()
    if "payload" not in form:
        raise HTTPException(status_code=400, detail="Missing payload")
    try:
        payload = json.loads(form["payload"])
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid payload JSON")

    if payload.get("type") != "block_actions":
        return Response(status_code=200)

    actions = payload.get("actions", [])
    if not actions:
        return Response(status_code=200)

    action_id: str = actions[0].get("action_id", "")

    # Parse action_id: hitl_update:{interaction_id}:{page_id}
    #                   hitl_create:{interaction_id}
    #                   hitl_cancel:{interaction_id}
    if not action_id.startswith(("hitl_update:", "hitl_create:", "hitl_cancel:")):
        return Response(status_code=200)

    parts = action_id.split(":", 3)
    action_type = parts[0]  # hitl_update / hitl_create / hitl_cancel
    interaction_id = parts[1] if len(parts) > 1 else ""
    target_page_id = parts[2] if len(parts) > 2 else ""

    pending = hitl_consume(interaction_id)
    if pending is None:
        # Already consumed or expired — update message to inform user
        ack_blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "⚠️ This confirmation has already been actioned or expired.",
                },
            }
        ]
        return Response(
            content=json.dumps({"replace_original": True, "blocks": ack_blocks}),
            media_type="application/json",
        )

    response_ts = pending.processing_ts or pending.thread_ts

    # Acknowledge immediately with a "processing" message
    ack_blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "⏳ Processing your choice..."},
        }
    ]
    ack_body = json.dumps({"replace_original": True, "blocks": ack_blocks})

    if action_type == "hitl_update":
        background_tasks.add_task(
            execute_update,
            pending.article_id,
            pending.article,
            target_page_id,
            pending.channel_id,
            response_ts,
        )
    elif action_type == "hitl_create":
        background_tasks.add_task(
            execute_create,
            pending.article_id,
            pending.article,
            pending.channel_id,
            response_ts,
        )
    else:  # hitl_cancel
        background_tasks.add_task(
            execute_cancel,
            pending.article,
            pending.channel_id,
            response_ts,
            pending.user_id,
        )

    return Response(content=ack_body, media_type="application/json")


class ExtractRequest(BaseModel):
    thread_text: str = Field(max_length=50_000)


@app.post("/extract", dependencies=[Depends(_require_api_key)])
async def extract_endpoint(body: ExtractRequest) -> dict:
    """Direct extraction — accepts raw thread text, returns KB article JSON."""
    article = extract(body.thread_text)
    return article.model_dump()


@app.get("/articles", dependencies=[Depends(_require_api_key)])
async def list_articles() -> list[dict]:
    """List all articles saved in the in-memory store."""
    return get_store().list_all()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
