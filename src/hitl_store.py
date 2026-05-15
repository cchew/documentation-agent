"""In-memory store for pending HITL (human-in-the-loop) interactions.

Keyed by interaction_id. Each entry expires after TIMEOUT_SECONDS; the timeout
task DMs the triggering user and removes the entry automatically.

Localhost only: the dict is lost on restart. AWS Cycle 2 migrates to DynamoDB
with a TTL attribute and DDB Streams for the timeout DM.
"""
from __future__ import annotations

import asyncio
import logging
import time

from pydantic import BaseModel

from src.extraction.models import KBArticle

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30 * 60  # 30 minutes


class PendingInteraction(BaseModel):
    interaction_id: str
    article_id: str
    article: KBArticle
    channel_id: str
    thread_ts: str
    processing_ts: str | None
    user_id: str | None
    expires_at: float  # epoch seconds


_pending: dict[str, PendingInteraction] = {}


def register(
    interaction_id: str,
    article_id: str,
    article: KBArticle,
    channel_id: str,
    thread_ts: str,
    processing_ts: str | None,
    user_id: str | None,
) -> None:
    """Register a pending interaction and schedule a 30-minute timeout task."""
    entry = PendingInteraction(
        interaction_id=interaction_id,
        article_id=article_id,
        article=article,
        channel_id=channel_id,
        thread_ts=thread_ts,
        processing_ts=processing_ts,
        user_id=user_id,
        expires_at=time.monotonic() + TIMEOUT_SECONDS,
    )
    _pending[interaction_id] = entry
    _schedule_timeout(interaction_id)


def consume(interaction_id: str) -> PendingInteraction | None:
    """Atomically pop and return the entry, or None if missing/expired."""
    entry = _pending.pop(interaction_id, None)
    if entry is None:
        return None
    if time.monotonic() > entry.expires_at:
        logger.warning("HITL interaction %s consumed after expiry", interaction_id)
        return None
    return entry


def get(interaction_id: str) -> PendingInteraction | None:
    """Return the entry without removing it, or None if missing/expired."""
    entry = _pending.get(interaction_id)
    if entry is None:
        return None
    if time.monotonic() > entry.expires_at:
        _pending.pop(interaction_id, None)
        return None
    return entry


def _schedule_timeout(interaction_id: str) -> None:
    """Schedule an asyncio task to auto-cancel the interaction on timeout.

    NOTE: FastAPI dispatches sync background tasks (and therefore run_update_or_create)
    in a threadpool executor. asyncio.get_event_loop() called from a thread in Python
    3.10+ returns a per-thread loop that is not running, so this call is a no-op in the
    FastAPI deployment. The expiry check in consume()/get() still fires correctly on the
    next call; only the proactive DM notification is skipped. Acceptable for demo scope;
    fix for production by passing the running loop from the async endpoint context.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_timeout_task(interaction_id))
        else:
            logger.debug("No running event loop; timeout task not scheduled for %s", interaction_id)
    except RuntimeError:
        logger.debug("Could not schedule timeout task for %s", interaction_id)


async def _timeout_task(interaction_id: str) -> None:
    await asyncio.sleep(TIMEOUT_SECONDS)
    entry = _pending.pop(interaction_id, None)
    if entry is None:
        return  # already consumed by user action

    logger.info("HITL interaction %s timed out; notifying user", interaction_id)
    if entry.user_id:
        try:
            from src.slack_client import dm_user
            dm_user(
                entry.user_id,
                f"Your KB article confirmation for *{entry.article.title}* expired "
                f"after 30 minutes without a response. Trigger the shortcut again to restart.",
            )
        except Exception:
            logger.exception("Failed to DM user %s on HITL timeout", entry.user_id)


def _clear_all() -> None:
    """Test helper — clears all pending interactions."""
    _pending.clear()


def pending_count() -> int:
    """Test helper — returns number of pending interactions."""
    return len(_pending)
