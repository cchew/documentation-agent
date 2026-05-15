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
@patch("src.update_or_create.hitl_register")
@patch("src.update_or_create.update_response")
@patch("src.update_or_create.create_page")
@patch("src.update_or_create.match")
def test_posts_confirmation_card_and_suspends_when_candidates_found(
    mock_match, mock_create_page, mock_update_response, mock_hitl_register, mock_get_kb_index
):
    """Matcher returns 1 candidate: interactive confirmation card posted, hitl_register called,
    create_page NOT called (execution suspended waiting for user)."""
    mock_match.return_value = MatchResult(candidates=[_candidate(0.5)])
    mock_get_kb_index.return_value = MagicMock()

    from src.update_or_create import run_update_or_create
    run_update_or_create("C1_1.2", _article(), "C1", "1.2")

    # Interactive card posted (once)
    assert mock_update_response.call_count == 1
    first_payload = mock_update_response.call_args[0][2]
    assert "hitl_create" in str(first_payload)

    # Suspended — no page created, register called
    mock_create_page.assert_not_called()
    mock_hitl_register.assert_called_once()


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
@patch("src.update_or_create.hitl_register")
@patch("src.update_or_create.update_response")
@patch("src.update_or_create.create_page")
@patch("src.update_or_create.match")
def test_confirmation_card_failure_still_registers(
    mock_match, mock_create_page, mock_update_response, mock_hitl_register, mock_get_kb_index
):
    """update_response raises posting the confirmation card: hitl_register still called,
    create_page still NOT called (suspended waiting for HITL even if card post failed)."""
    mock_match.return_value = MatchResult(candidates=[_candidate(0.5)])
    mock_get_kb_index.return_value = MagicMock()
    mock_update_response.side_effect = RuntimeError("Slack down")

    from src.update_or_create import run_update_or_create
    run_update_or_create("C1_1.2", _article(), "C1", "1.2")

    mock_create_page.assert_not_called()
    mock_hitl_register.assert_called_once()


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
