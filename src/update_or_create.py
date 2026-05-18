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
    build_processing_ack,
)
from src.confluence_client import create_page, get_page, post_page_comment, update_page
from src.doco_agent_core.kb_index import KBIndex, KBIndexEntry
from src.doco_agent_core.matcher import build_embed_text, match
from src.doco_agent_core.models import MatchResult, ProtectedField
from src.extraction.models import KBArticle
from src.hitl_store import register as hitl_register
from src.run_log import log_run
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
        # Refresh candidate titles from Confluence — index titles go stale after manual edits
        refreshed = []
        for c in result.candidates:
            try:
                page_data = get_page(c.page_id)
                refreshed.append(c.model_copy(update={"title": page_data.get("title", c.title)}))
            except Exception:
                refreshed.append(c)
        result = MatchResult(candidates=refreshed)

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
    try:
        update_response(channel_id, response_ts, build_processing_ack())
    except Exception:
        logger.warning("Failed to post processing ack for create; continuing")
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

    # Acknowledge immediately so the HITL card updates before the slow Confluence calls
    try:
        update_response(channel_id, response_ts, build_processing_ack())
    except Exception:
        logger.warning("Failed to post processing ack for update; continuing")

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

    # Detect human edits by version number: any version beyond the last agent-indexed
    # version is a human edit, regardless of author (avoids same-account email match failure).
    last_agent_version = stored_entry.last_indexed_version if stored_entry else 0
    human_edited = current_version > last_agent_version

    # Three-way merge: protect non-empty scalar fields when base exists (prevents
    # both human-edit overwrites and LLM output drift on re-runs).
    merged, protected = _three_way_merge(base_article, article, human_edited)

    # Preserve the live Confluence title when humans have edited the page.
    # The merge keeps base.title, but base = last agent write — not the human's edit.
    if human_edited:
        current_title = page_data.get("title")
        if current_title and current_title != merged.title:
            merged = merged.model_copy(update={"title": current_title})

    # Write back to Confluence
    try:
        confluence_url = update_page(target_page_id, merged, current_version)
    except Exception:
        logger.exception("Confluence update failed for page %s", target_page_id)
        from src.block_kit import build_error_response
        update_response(channel_id, response_ts, build_error_response("Failed to update the Confluence page."))
        try:
            log_run(action="update", target_page_id=target_page_id, match_candidates=[], protected_fields=[], status="error", error_message="Confluence update_page failed")
        except Exception:
            logger.exception("run_log write failed; continuing")
        return

    if human_edited:
        _post_protected_field_comments(target_page_id, protected)

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
    try:
        log_run(
            action="update",
            target_page_id=target_page_id,
            match_candidates=[],  # TODO(cycle-2): thread candidates from run_update_or_create
            protected_fields=[p.field_name for p in protected],
            status="success",
        )
    except Exception:
        logger.exception("run_log write failed; continuing")


def execute_cancel(
    article: KBArticle,
    channel_id: str,
    response_ts: str,
    user_id: str | None,
) -> None:
    """Notify the user that no article was published."""
    try:
        update_response(channel_id, response_ts, build_processing_ack())
    except Exception:
        logger.warning("Failed to post processing ack for cancel; continuing")
    from src.block_kit import build_error_response
    try:
        update_response(
            channel_id,
            response_ts,
            build_error_response(f"Cancelled — *{article.title}* was not published."),
        )
    except Exception:
        logger.exception("Failed to post cancel confirmation card")
    try:
        log_run(action="cancel", target_page_id=None, match_candidates=[], protected_fields=[], status="success")
    except Exception:
        logger.exception("run_log write failed; continuing")
    if user_id:
        try:
            dm_user(user_id, f"You cancelled the KB article publication for *{article.title}*.")
        except Exception:
            logger.exception("Failed to DM user %s on cancel", user_id)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _post_protected_field_comments(
    page_id: str,
    protected: list[ProtectedField],
) -> None:
    """Post a Confluence comment listing scalar fields the agent wanted to update but couldn't."""
    if not protected:
        return
    lines = [
        "<p>[Doc Agent] <strong>Documentation Agent</strong> suggested the following updates "
        "to protected fields (not applied — this page has been manually edited). "
        "Please review and apply if appropriate:</p><ul>"
    ]
    for field in protected:
        lines.append(
            f"<li><strong>{field.field_name}:</strong> "
            f"&ldquo;{field.draft_value}&rdquo;</li>"
        )
    lines.append("</ul>")
    try:
        post_page_comment(page_id, "".join(lines))
    except Exception:
        logger.exception("Failed to post protected-field comment on %s; continuing", page_id)


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
    try:
        log_run(action="create", target_page_id=page_id, match_candidates=[], protected_fields=[], status="success")
    except Exception:
        logger.exception("run_log write failed; continuing")


_PROTECTED_SCALAR_FIELDS: tuple[str, ...] = (
    "title", "summary", "resolution", "root_cause", "severity",
)


def _three_way_merge(
    base: KBArticle | None,
    draft: KBArticle,
    human_edited: bool,
) -> tuple[KBArticle, list[ProtectedField]]:
    """
    Three-way merge: base = last agent write, draft = new agent output.

    If base is None → first write, clean overwrite.
    If base exists → union list fields; protect non-empty scalar fields regardless of
    whether the edits were human or agent-driven (prevents LLM output drift on re-runs).
    Protected fields are surfaced as Confluence comments only when human_edited=True.
    """
    if base is None:
        return draft, []

    # Base exists: union list fields, protect non-empty scalar fields
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

    protected: list[ProtectedField] = []
    for field in _PROTECTED_SCALAR_FIELDS:
        base_val = str(getattr(base, field, None) or "")
        draft_val = str(getattr(draft, field, None) or "")
        if base_val != draft_val:
            protected.append(ProtectedField(
                field_name=field,
                base_value=getattr(base, field, None),
                draft_value=getattr(draft, field, None),
            ))

    return KBArticle.model_validate(merged_data), protected


def _union_list(existing: list, additions: list) -> list:
    seen = set(existing)
    result = list(existing)
    for item in additions:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result
