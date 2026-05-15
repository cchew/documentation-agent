from unittest.mock import MagicMock, call, patch

import pytest

from src.doco_agent_core.models import MatchCandidate, MatchResult
from src.extraction.models import KBArticle


def _article() -> KBArticle:
    return KBArticle(
        title="Auth service outage",
        summary="IAM role expired causing auth failures",
        incident_type="incident",
        systems_affected=["auth-service"],
        steps_taken=["rotated IAM role", "redeployed service"],
        resolution="Rotated credentials",
        tags=["auth", "iam"],
        related_topics=["credentials"],
        confidence_score=0.9,
        extraction_viable=True,
        pii_detected=False,
    )


def _candidate(score: float = 0.5) -> MatchCandidate:
    return MatchCandidate(
        page_id="page-1",
        title="IAM Auth Failure",
        score=score,
        score_label="Possible match",
        reason="Similar content",
    )


@pytest.fixture(autouse=True)
def reset_store():
    from src.storage import get_store
    get_store.cache_clear()
    yield
    get_store.cache_clear()


@patch("src.update_or_create._get_kb_index")
@patch("src.update_or_create.get_store")
@patch("src.update_or_create.update_response")
@patch("src.update_or_create.create_page")
@patch("src.update_or_create.match")
def test_creates_new_article_no_candidates(
    mock_match, mock_create_page, mock_update_response, mock_get_store, mock_get_kb_index
):
    """No candidates: create_page called once, update_response once (KB card), no match card."""
    mock_match.return_value = MatchResult(candidates=[])
    mock_create_page.return_value = ("https://confluence.example.com/page/1", "page-1")

    mock_store = MagicMock()
    mock_store.get_page_id.return_value = None
    mock_get_store.return_value = mock_store

    mock_kb_index = MagicMock()
    mock_kb_index.search.return_value = []
    mock_get_kb_index.return_value = mock_kb_index

    from src.update_or_create import run_update_or_create
    run_update_or_create("C1_1.2", _article(), "C1", "1.2")

    mock_create_page.assert_called_once()
    mock_update_response.assert_called_once()
    # Verify it's the KB card (not a match card)
    posted_payload = mock_update_response.call_args[0][2]
    assert "Similar articles found" not in str(posted_payload)
    mock_kb_index.save.assert_called_once()


@patch("src.update_or_create._get_kb_index")
@patch("src.update_or_create.get_store")
@patch("src.update_or_create.update_response")
@patch("src.update_or_create.create_page")
@patch("src.update_or_create.match")
def test_posts_match_card_when_candidates_found(
    mock_match, mock_create_page, mock_update_response, mock_get_store, mock_get_kb_index
):
    """Matcher returns 1 candidate: update_response called twice (match card first, KB card second)."""
    mock_match.return_value = MatchResult(candidates=[_candidate(0.5)])
    mock_create_page.return_value = ("https://confluence.example.com/page/2", "page-2")

    mock_store = MagicMock()
    mock_store.get_page_id.return_value = None
    mock_get_store.return_value = mock_store

    mock_kb_index = MagicMock()
    mock_kb_index.search.return_value = []
    mock_get_kb_index.return_value = mock_kb_index

    from src.update_or_create import run_update_or_create
    run_update_or_create("C1_1.2", _article(), "C1", "1.2")

    assert mock_update_response.call_count == 2
    # First call is the match card
    first_payload = mock_update_response.call_args_list[0][0][2]
    assert "Similar articles found" in str(first_payload)
    # Second call is the KB card
    mock_create_page.assert_called_once()


@patch("src.update_or_create._get_kb_index")
@patch("src.update_or_create.get_store")
@patch("src.update_or_create.update_response")
@patch("src.update_or_create.create_page")
@patch("src.update_or_create.match")
def test_idempotent_skips_create_when_page_exists(
    mock_match, mock_create_page, mock_update_response, mock_get_store, mock_get_kb_index
):
    """Store already has page_id: create_page NOT called."""
    mock_match.return_value = MatchResult(candidates=[])

    mock_store = MagicMock()
    mock_store.get_page_id.return_value = "existing-page-id"
    mock_get_store.return_value = mock_store

    mock_kb_index = MagicMock()
    mock_kb_index.search.return_value = []
    mock_get_kb_index.return_value = mock_kb_index

    from src.update_or_create import run_update_or_create
    run_update_or_create("C1_1.2", _article(), "C1", "1.2")

    mock_create_page.assert_not_called()


@patch("src.update_or_create._get_kb_index")
@patch("src.update_or_create.get_store")
@patch("src.update_or_create.update_response")
@patch("src.update_or_create.create_page")
@patch("src.update_or_create.match")
def test_match_card_failure_does_not_abort(
    mock_match, mock_create_page, mock_update_response, mock_get_store, mock_get_kb_index
):
    """update_response raises on first call (match card), but create_page still called."""
    mock_match.return_value = MatchResult(candidates=[_candidate(0.5)])
    mock_create_page.return_value = ("https://confluence.example.com/page/3", "page-3")

    mock_store = MagicMock()
    mock_store.get_page_id.return_value = None
    mock_get_store.return_value = mock_store

    mock_kb_index = MagicMock()
    mock_kb_index.search.return_value = []
    mock_get_kb_index.return_value = mock_kb_index

    # First call (match card) raises, second call (KB card) succeeds
    mock_update_response.side_effect = [RuntimeError("Slack down"), None]

    from src.update_or_create import run_update_or_create
    run_update_or_create("C1_1.2", _article(), "C1", "1.2")

    mock_create_page.assert_called_once()
    # update_response called twice: once for match card (raised), once for KB card
    assert mock_update_response.call_count == 2


@patch("src.update_or_create._get_kb_index")
@patch("src.update_or_create.get_store")
@patch("src.update_or_create.update_response")
@patch("src.update_or_create.create_page")
@patch("src.update_or_create.match")
def test_index_failure_does_not_abort(
    mock_match, mock_create_page, mock_update_response, mock_get_store, mock_get_kb_index
):
    """kb_index.save raises: create_page still called, update_response called for KB card, no exception propagates."""
    mock_match.return_value = MatchResult(candidates=[])
    mock_create_page.return_value = ("https://confluence.example.com/page/4", "page-4")

    mock_store = MagicMock()
    mock_store.get_page_id.return_value = None
    mock_get_store.return_value = mock_store

    mock_kb_index = MagicMock()
    mock_kb_index.search.return_value = []
    mock_kb_index.save.side_effect = RuntimeError("DB write failed")
    mock_get_kb_index.return_value = mock_kb_index

    from src.update_or_create import run_update_or_create
    # Should not raise
    run_update_or_create("C1_1.2", _article(), "C1", "1.2")

    mock_create_page.assert_called_once()
    # update_response called once for KB card (no match card since no candidates)
    assert mock_update_response.call_count == 1
    posted_payload = mock_update_response.call_args[0][2]
    assert "Similar articles found" not in str(posted_payload)
