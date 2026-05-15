"""Cycle 1 update-or-create entry point — sub-part (a): create path with match candidates card."""
import logging
import os

from src.block_kit import build_kb_response, build_match_candidates_card
from src.confluence_client import create_page
from src.doco_agent_core.kb_index import KBIndex, KBIndexEntry
from src.doco_agent_core.matcher import build_embed_text, match
from src.extraction.models import KBArticle
from src.slack_client import update_response
from src.storage import get_store

logger = logging.getLogger(__name__)

_KB_INDEX_PATH = os.environ.get("KB_INDEX_PATH", "var/kb-index.db")
_CONFLUENCE_SPACE_KEY = os.environ.get("CONFLUENCE_SPACE_KEY", "")


def _get_kb_index() -> KBIndex:
    return KBIndex(db_path=_KB_INDEX_PATH)


def run_update_or_create(
    article_id: str,
    article: KBArticle,
    channel_id: str,
    thread_ts: str,
) -> None:
    store = get_store()
    kb_index = _get_kb_index()
    space_key = _CONFLUENCE_SPACE_KEY or None

    # Stage: match
    result = match(article, channel_id, thread_ts, kb_index, space_key=space_key)

    # Post read-only card if candidates found
    if result.has_candidates:
        try:
            card = build_match_candidates_card(result.candidates)
            update_response(channel_id, thread_ts, card)
        except Exception:
            logger.exception("Failed to post match candidates card; continuing")

    # Idempotency: reuse existing page if already created
    existing_page_id = store.get_page_id(article_id)
    if existing_page_id:
        logger.info("Reusing Confluence page %s for %s", existing_page_id, article_id)
        return

    # Create new Confluence page
    confluence_url, page_id = create_page(article)
    store.save_page_id(article_id, page_id)

    # Post KB result card
    payload = build_kb_response(article, confluence_url)
    update_response(channel_id, thread_ts, payload)

    # Index for future matcher queries
    entry = KBIndexEntry(
        page_id=page_id,
        space_key=space_key or "",
        title=article.title,
        incident_type=article.incident_type,
        systems_affected=article.systems_affected,
        confluence_url=confluence_url,
    )
    embed_text = build_embed_text(article)
    try:
        kb_index.save(entry, embed_text)
    except Exception:
        logger.exception("Failed to index article %s; continuing", page_id)
