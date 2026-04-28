from src.extraction.models import KBArticle
from src.storage.base import ArticleStore


class MemoryStore(ArticleStore):
    def __init__(self) -> None:
        self._articles: dict[str, KBArticle] = {}
        self._page_ids: dict[str, str] = {}

    def save(self, article_id: str, article: KBArticle) -> None:
        self._articles[article_id] = article

    def save_page_id(self, article_id: str, page_id: str) -> None:
        self._page_ids[article_id] = page_id

    def get(self, article_id: str) -> KBArticle | None:
        return self._articles.get(article_id)

    def get_page_id(self, article_id: str) -> str | None:
        return self._page_ids.get(article_id)

    def list_all(self) -> list[dict]:
        return [{"id": k, **v.model_dump()} for k, v in self._articles.items()]

    def clear(self) -> None:
        self._articles.clear()
        self._page_ids.clear()
