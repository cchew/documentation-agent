"""Cycle 1 update-or-create entry point. Stub — not yet implemented."""
from src.extraction.models import KBArticle


def run_update_or_create(
    article_id: str,
    article: KBArticle,
    channel_id: str,
    thread_ts: str,
) -> None:
    raise NotImplementedError(
        "UPDATE_NOT_DUPLICATE=true requires Cycle 1 implementation"
    )
