from abc import ABC, abstractmethod
from src.extraction.models import KBArticle


class ArticleStore(ABC):
    @abstractmethod
    def save(self, article_id: str, article: KBArticle) -> None: ...

    @abstractmethod
    def save_page_id(self, article_id: str, page_id: str) -> None: ...

    @abstractmethod
    def get(self, article_id: str) -> KBArticle | None: ...

    @abstractmethod
    def get_page_id(self, article_id: str) -> str | None: ...

    @abstractmethod
    def list_all(self) -> list[dict]: ...

    @abstractmethod
    def clear(self) -> None: ...
