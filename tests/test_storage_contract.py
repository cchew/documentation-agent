import pytest
from src.extraction.models import KBArticle
from src.storage.memory import MemoryStore


def _sample_article() -> KBArticle:
    return KBArticle(
        title="t", summary="s", incident_type="incident",
        systems_affected=["x"], steps_taken=["a"], resolution="r",
        tags=["k"], related_topics=["rt"],
        confidence_score=0.9, extraction_viable=True, pii_detected=False,
    )


@pytest.fixture
def store():
    return MemoryStore()


def test_save_and_get(store):
    store.save("id1", _sample_article())
    got = store.get("id1")
    assert got is not None and got.title == "t"


def test_get_missing_returns_none(store):
    assert store.get("missing") is None


def test_save_page_id_and_get_page_id(store):
    store.save("id1", _sample_article())
    store.save_page_id("id1", "page-123")
    assert store.get_page_id("id1") == "page-123"


def test_get_page_id_missing(store):
    assert store.get_page_id("nope") is None


def test_list_all_returns_dicts(store):
    store.save("id1", _sample_article())
    rows = store.list_all()
    assert len(rows) == 1
    assert rows[0]["id"] == "id1"
    assert rows[0]["title"] == "t"


def test_clear(store):
    store.save("id1", _sample_article())
    store.clear()
    assert store.get("id1") is None
    assert store.list_all() == []
