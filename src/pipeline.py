"""Cloud-neutral pipeline: Slack thread -> KB article -> Confluence + storage."""
import logging

from src.block_kit import build_error_response, build_kb_response, build_not_viable_response
from src.confluence_client import create_page
from src.extraction.extractor import extract
from src.slack_client import fetch_thread, update_response
from src.storage import get_store

logger = logging.getLogger(__name__)


def run_pipeline(channel_id: str, thread_ts: str, processing_ts: str | None) -> None:
    """
    Fetch the thread, extract a KB article, persist, and (if processing_ts is set)
    update the Slack in-progress message.

    Idempotent: if a Confluence page already exists for the article_id, reuses it.
    Errors are logged and surfaced to Slack via update_response when processing_ts is set;
    the function does not re-raise — Lambda retry semantics are owned by the caller.
    """
    article_id = f"{channel_id}_{thread_ts}"
    store = get_store()

    try:
        thread_text = fetch_thread(channel_id, thread_ts)
        article = extract(thread_text)
        store.save(article_id, article)

        if article.extraction_viable:
            existing_page_id = store.get_page_id(article_id)
            if existing_page_id:
                logger.info("Reusing Confluence page %s for %s", existing_page_id, article_id)
                return
            confluence_url, page_id = create_page(article)
            store.save_page_id(article_id, page_id)
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

    if processing_ts is not None:
        try:
            update_response(channel_id, processing_ts, payload)
        except Exception:
            logger.exception("Slack update_response failed; article state is preserved")
