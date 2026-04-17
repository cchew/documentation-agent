"""
In-memory article store keyed by article_id (channel_ts).
Acceptable for demo — no persistence across restarts.
"""
from extraction.models import KBArticle

_store: dict[str, KBArticle] = {}
_page_ids: dict[str, str] = {}  # article_id → confluence page_id


def save(article_id: str, article: KBArticle) -> None:
    _store[article_id] = article


def save_page_id(article_id: str, page_id: str) -> None:
    _page_ids[article_id] = page_id


def get(article_id: str) -> KBArticle | None:
    return _store.get(article_id)


def list_all() -> list[dict]:
    return [
        {"id": k, **v.model_dump()}
        for k, v in _store.items()
    ]


def list_page_ids() -> list[str]:
    return list(_page_ids.values())
