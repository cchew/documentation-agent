"""Cycle 1 update-or-create entry point.

Sub-part (a): create path with read-only match candidates card (no candidates → create immediately).
Sub-part (b): interactive HITL card when candidates found; three-way merge on update.
"""
from __future__ import annotations

import json
import logging
import os

from src.block_kit import (
    build_kb_response,
    build_match_candidates_card,
    build_match_confirmation_card,
)
from src.confluence_client import create_page, get_page, has_human_edits_since, update_page
from src.doco_agent_core.kb_index import KBIndex, KBIndexEntry
from src.doco_agent_core.matcher import build_embed_text, match
from src.extraction.models import KBArticle
from src.hitl_store import register as hitl_register
from src.slack_client import dm_user, update_response
from src.storage import get_store

logger = logging.getLogger(__name__)

_KB_INDEX_PATH = os.environ.get("KB_INDEX_PATH", "var/kb-index.db")
_CONFLUENCE_SPACE_KEY = os.environ.get("CONFLUENCE_SPACE_KEY", "")


def _get_kb_index() -> KBIndex:
    return KBIndex(db_path=_KB_INDEX_PATH)


# ---------------------------------------------------------------------------
# Entry point (called by pipeline)
# ---------------------------------------------------------------------------

def run_update_or_create(
    article_id: str,
    article: KBArticle,
    channel_id: str,
    thread_ts: str,
    processing_ts: str | None = None,
    user_id: str | None = None,
) -> None:
    store = get_store()
    kb_index = _get_kb_index()
    space_key = _CONFLUENCE_SPACE_KEY or None

    result = match(article, channel_id, thread_ts, kb_index, space_key=space_key)

    if result.has_candidates:
        interaction_id = f"hitl_{article_id}"
        card = build_match_confirmation_card(
            result.candidates, interaction_id, result.has_strong_match
        )
        response_ts = processing_ts or thread_ts
        try:
            update_response(channel_id, response_ts, card)
        except Exception:
            logger.exception("Failed to post HITL confirmation card; continuing")
        hitl_register(
            interaction_id=interaction_id,
            article_id=article_id,
            article=article,
            channel_id=channel_id,
            thread_ts=thread_ts,
            processing_ts=processing_ts,
            user_id=user_id,
        )
        return  # suspend — wait for /slack/interactions

    # No candidates above threshold: create immediately (same as sub-part a)
    existing_page_id = store.get_page_id(article_id)
    if existing_page_id:
        logger.info("Reusing Confluence page %s for %s", existing_page_id, article_id)
        return

    _do_create(article_id, article, channel_id, processing_ts or thread_ts, kb_index, space_key)


# ---------------------------------------------------------------------------
# Interaction handlers (called from /slack/interactions)
# ---------------------------------------------------------------------------

def execute_create(
    article_id: str,
    article: KBArticle,
    channel_id: str,
    response_ts: str,
    kb_index: KBIndex | None = None,
    space_key: str | None = None,
) -> None:
    """Create a new Confluence page and post the result card."""
    if kb_index is None:
        kb_index = _get_kb_index()
    if space_key is None:
        space_key = _CONFLUENCE_SPACE_KEY or None
    _do_create(article_id, article, channel_id, response_ts, kb_index, space_key)


def execute_update(
    article_id: str,
    article: KBArticle,
    target_page_id: str,
    channel_id: str,
    response_ts: str,
    kb_index: KBIndex | None = None,
    space_key: str | None = None,
) -> None:
    """Three-way merge the new draft into an existing Confluence page, then post result card."""
    if kb_index is None:
        kb_index = _get_kb_index()
    if space_key is None:
        space_key = _CONFLUENCE_SPACE_KEY or None

    # Fetch current page state
    try:
        page_data = get_page(target_page_id)
    except Exception:
        logger.exception("Failed to fetch target page %s; falling back to create", target_page_id)
        _do_create(article_id, article, channel_id, response_ts, kb_index, space_key)
        return

    current_version: int = page_data.get("version", {}).get("number", 0)

    # Load base (last agent-written draft) from kb_index
    stored_entry = kb_index.get(target_page_id)
    base_article: KBArticle | None = None
    if stored_entry and stored_entry.draft_json and stored_entry.draft_json != "{}":
        try:
            base_article = KBArticle.model_validate_json(stored_entry.draft_json)
        except Exception:
            logger.warning("Could not parse stored draft_json for %s; treating as no base", target_page_id)

    # Detect human edits via Confluence version history
    last_agent_version = stored_entry.last_indexed_version if stored_entry else 0
    human_edited = False
    try:
        human_edited = has_human_edits_since(target_page_id, since_version=last_agent_version)
    except Exception:
        logger.warning("Could not check human edits for %s; assuming no edits", target_page_id)

    # Three-way merge: only apply draft fields that haven't been human-edited
    merged = _three_way_merge(base_article, article, human_edited)

    # Write back to Confluence
    try:
        confluence_url = update_page(target_page_id, merged, current_version)
    except Exception:
        logger.exception("Confluence update failed for page %s", target_page_id)
        from src.block_kit import build_error_response
        update_response(channel_id, response_ts, build_error_response("Failed to update the Confluence page."))
        return

    # Re-index with the new draft
    store = get_store()
    store.save_page_id(article_id, target_page_id)
    entry = KBIndexEntry(
        page_id=target_page_id,
        space_key=space_key or "",
        title=merged.title,
        incident_type=merged.incident_type,
        systems_affected=merged.systems_affected,
        confluence_url=confluence_url,
        last_indexed_version=current_version + 1,
        draft_json=merged.model_dump_json(),
    )
    embed_text = build_embed_text(merged)
    try:
        kb_index.save(entry, embed_text)
    except Exception:
        logger.exception("Failed to re-index updated article %s; continuing", target_page_id)

    payload = build_kb_response(merged, confluence_url)
    update_response(channel_id, response_ts, payload)


def execute_cancel(
    article: KBArticle,
    channel_id: str,
    response_ts: str,
    user_id: str | None,
) -> None:
    """Notify the user that no article was published."""
    from src.block_kit import build_error_response
    update_response(
        channel_id,
        response_ts,
        build_error_response(f"Cancelled — *{article.title}* was not published."),
    )
    if user_id:
        try:
            dm_user(user_id, f"You cancelled the KB article publication for *{article.title}*.")
        except Exception:
            logger.exception("Failed to DM user %s on cancel", user_id)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _do_create(
    article_id: str,
    article: KBArticle,
    channel_id: str,
    response_ts: str,
    kb_index: KBIndex,
    space_key: str | None,
) -> None:
    store = get_store()

    existing_page_id = store.get_page_id(article_id)
    if existing_page_id:
        logger.info("Reusing Confluence page %s for %s", existing_page_id, article_id)
        return

    confluence_url, page_id = create_page(article)
    store.save_page_id(article_id, page_id)

    entry = KBIndexEntry(
        page_id=page_id,
        space_key=space_key or "",
        title=article.title,
        incident_type=article.incident_type,
        systems_affected=article.systems_affected,
        confluence_url=confluence_url,
        last_indexed_version=1,
        draft_json=article.model_dump_json(),
    )
    embed_text = build_embed_text(article)
    try:
        kb_index.save(entry, embed_text)
    except Exception:
        logger.exception("Failed to index article %s; continuing", page_id)

    payload = build_kb_response(article, confluence_url)
    update_response(channel_id, response_ts, payload)


def _three_way_merge(
    base: KBArticle | None,
    draft: KBArticle,
    human_edited: bool,
) -> KBArticle:
    """
    Three-way merge: base = last agent write, draft = new agent output, current = live page.

    If no human edits detected → clean overwrite with draft.
    If human edits detected → protect scalar fields, union-merge list fields.
    Protected fields are skipped here; sub-part (c) adds comment-back to Confluence.
    """
    if not human_edited or base is None:
        return draft

    # Human edits exist: union list fields, protect scalar fields (keep base values)
    merged_data = base.model_dump()

    # Union-merge list fields: add new draft items, never remove existing
    for field in ("systems_affected", "steps_taken", "tags", "related_topics", "action_items", "prerequisites"):
        base_list: list = merged_data.get(field) or []
        draft_list: list = getattr(draft, field, None) or []
        merged_data[field] = _union_list(base_list, draft_list)

    # Always update confidence_score and viability from the fresh extraction
    merged_data["confidence_score"] = draft.confidence_score
    merged_data["extraction_viable"] = draft.extraction_viable
    merged_data["pii_detected"] = draft.pii_detected
    merged_data["pii_fields"] = draft.pii_fields

    return KBArticle.model_validate(merged_data)


def _union_list(existing: list, additions: list) -> list:
    seen = set(existing)
    result = list(existing)
    for item in additions:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result
