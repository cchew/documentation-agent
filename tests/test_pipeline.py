from unittest.mock import patch, MagicMock
import pytest
from src.extraction.models import KBArticle
from src.pipeline import run_pipeline


def _viable_article() -> KBArticle:
    return KBArticle(
        title="t", summary="s", incident_type="incident",
        systems_affected=["x"], steps_taken=["a"], resolution="r",
        tags=["k"], related_topics=["rt"],
        confidence_score=0.9, extraction_viable=True, pii_detected=False,
    )


@pytest.fixture(autouse=True)
def reset_store():
    from src.storage import get_store
    get_store.cache_clear()
    yield
    get_store.cache_clear()


@patch("src.pipeline.update_response")
@patch("src.pipeline.create_page")
@patch("src.pipeline.extract")
@patch("src.pipeline.fetch_thread")
def test_viable_article_creates_confluence_page_and_saves(
    mock_fetch, mock_extract, mock_create, mock_update
):
    mock_fetch.return_value = "thread text"
    mock_extract.return_value = _viable_article()
    mock_create.return_value = ("https://conf/x", "page-1")

    run_pipeline("C1", "1.2", "p.1")

    mock_create.assert_called_once()
    mock_update.assert_called_once()
    from src.storage import get_store
    assert get_store().get_page_id("C1_1.2") == "page-1"


@patch("src.pipeline.update_response")
@patch("src.pipeline.create_page")
@patch("src.pipeline.extract")
@patch("src.pipeline.fetch_thread")
def test_idempotency_skips_confluence_create_when_page_id_exists(
    mock_fetch, mock_extract, mock_create, mock_update
):
    mock_fetch.return_value = "thread text"
    mock_extract.return_value = _viable_article()
    mock_create.return_value = ("https://conf/x", "page-1")

    from src.storage import get_store
    get_store().save_page_id("C1_1.2", "existing-page")

    run_pipeline("C1", "1.2", "p.1")

    mock_create.assert_not_called()


@patch("src.pipeline.update_response")
@patch("src.pipeline.extract")
@patch("src.pipeline.fetch_thread")
def test_not_viable_skips_confluence(mock_fetch, mock_extract, mock_update):
    mock_fetch.return_value = "thread text"
    article = _viable_article()
    article.extraction_viable = False
    mock_extract.return_value = article

    run_pipeline("C1", "1.2", "p.1")

    mock_update.assert_called_once()


@patch("src.pipeline.update_response")
@patch("src.pipeline.extract")
@patch("src.pipeline.fetch_thread")
def test_no_processing_ts_skips_slack_update(mock_fetch, mock_extract, mock_update):
    mock_fetch.return_value = "thread text"
    article = _viable_article()
    article.extraction_viable = False
    mock_extract.return_value = article

    run_pipeline("C1", "1.2", None)

    mock_update.assert_not_called()
