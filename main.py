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

import storage
from block_kit import build_error_response, build_kb_response, build_not_viable_response
from confluence_client import create_page
from extraction.extractor import extract
from slack_client import fetch_thread, post_processing, post_response, update_response, verify_signature

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
# Background pipeline
# ---------------------------------------------------------------------------

def _run_pipeline(channel_id: str, thread_ts: str, processing_ts: str) -> None:
    """Fetch thread, extract KB article, update the in-progress message with result."""
    try:
        thread_text = fetch_thread(channel_id, thread_ts)
        article = extract(thread_text)

        article_id = f"{channel_id}_{thread_ts}"
        storage.save(article_id, article)

        if article.extraction_viable:
            confluence_url, page_id = create_page(article)
            storage.save_page_id(article_id, page_id)
            payload = build_kb_response(article, confluence_url)
        else:
            payload = build_not_viable_response(article)

    except RuntimeError as e:
        logger.error("Pipeline runtime error: %s", e)
        payload = build_error_response("Could not fetch or post to Slack. Check bot permissions.")
    except ValueError as e:
        logger.error("Pipeline extraction error: %s", e)
        payload = build_error_response("Extraction failed — the thread may be in an unexpected format.")
    except Exception:
        logger.exception("Unexpected pipeline error")
        payload = build_error_response("An unexpected error occurred.")

    update_response(channel_id, processing_ts, payload)


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
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Missing field in payload: {e}") from e

    processing_ts = post_processing(channel_id, thread_ts)
    background_tasks.add_task(_run_pipeline, channel_id, thread_ts, processing_ts)
    return Response(status_code=200)


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
    return storage.list_all()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
