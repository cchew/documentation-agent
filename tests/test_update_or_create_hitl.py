"""Tests for sub-part (b): interactive HITL flow in update_or_create."""
from unittest.mock import MagicMock, patch

import pytest

from src.doco_agent_core.models import MatchCandidate, MatchResult
from src.extraction.models import KBArticle
from src.hitl_store import _clear_all, pending_count


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


def _candidate(score: float = 0.5, page_id: str = "page-1") -> MatchCandidate:
    label = "Strong match" if score >= 0.85 else "Possible match"
    return MatchCandidate(
        page_id=page_id,
        title="IAM Auth Failure",
        score=score,
        score_label=label,
        reason="Similar content",
    )


@pytest.fixture(autouse=True)
def reset_stores():
    from src.storage import get_store
    get_store.cache_clear()
    _clear_all()
    yield
    get_store.cache_clear()
    _clear_all()


# ---------------------------------------------------------------------------
# run_update_or_create — HITL path (candidates found)
# ---------------------------------------------------------------------------

@patch("src.update_or_create._get_kb_index")
@patch("src.update_or_create.hitl_register")
@patch("src.update_or_create.update_response")
@patch("src.update_or_create.match")
def test_hitl_path_posts_confirmation_card_and_registers(
    mock_match, mock_update_response, mock_hitl_register, mock_get_kb_index
):
    mock_match.return_value = MatchResult(candidates=[_candidate(0.5)])
    mock_get_kb_index.return_value = MagicMock()

    from src.update_or_create import run_update_or_create
    run_update_or_create("C1_1.2", _article(), "C1", "1.2", processing_ts="proc-ts", user_id="U1")

    mock_update_response.assert_called_once()
    posted = mock_update_response.call_args[0][2]
    # Confirmation card (not the old read-only card)
    assert "hitl_create" in str(posted)
    assert "hitl_cancel" in str(posted)

    mock_hitl_register.assert_called_once()
    call_kwargs = mock_hitl_register.call_args
    assert call_kwargs.kwargs["interaction_id"] == "hitl_C1_1.2"
    assert call_kwargs.kwargs["user_id"] == "U1"
    assert call_kwargs.kwargs["processing_ts"] == "proc-ts"


@patch("src.update_or_create._get_kb_index")
@patch("src.update_or_create.create_page")
@patch("src.update_or_create.get_store")
@patch("src.update_or_create.update_response")
@patch("src.update_or_create.match")
def test_no_candidates_creates_immediately(
    mock_match, mock_update_response, mock_get_store, mock_create_page, mock_get_kb_index
):
    mock_match.return_value = MatchResult(candidates=[])
    mock_create_page.return_value = ("https://confluence.example.com/page/1", "page-1")
    mock_store = MagicMock()
    mock_store.get_page_id.return_value = None
    mock_get_store.return_value = mock_store
    mock_get_kb_index.return_value = MagicMock()

    from src.update_or_create import run_update_or_create
    run_update_or_create("C1_1.2", _article(), "C1", "1.2")

    mock_create_page.assert_called_once()
    mock_update_response.assert_called_once()


@patch("src.update_or_create._get_kb_index")
@patch("src.update_or_create.hitl_register")
@patch("src.update_or_create.update_response")
@patch("src.update_or_create.match")
def test_hitl_card_post_failure_still_registers(
    mock_match, mock_update_response, mock_hitl_register, mock_get_kb_index
):
    mock_match.return_value = MatchResult(candidates=[_candidate(0.9)])
    mock_get_kb_index.return_value = MagicMock()
    mock_update_response.side_effect = RuntimeError("Slack down")

    from src.update_or_create import run_update_or_create
    # Should not raise
    run_update_or_create("C1_1.2", _article(), "C1", "1.2")

    mock_hitl_register.assert_called_once()


@patch("src.update_or_create._get_kb_index")
@patch("src.update_or_create.hitl_register")
@patch("src.update_or_create.update_response")
@patch("src.update_or_create.match")
def test_uses_processing_ts_for_update_response(
    mock_match, mock_update_response, mock_hitl_register, mock_get_kb_index
):
    mock_match.return_value = MatchResult(candidates=[_candidate(0.5)])
    mock_get_kb_index.return_value = MagicMock()

    from src.update_or_create import run_update_or_create
    run_update_or_create("C1_1.2", _article(), "C1", "thread-ts", processing_ts="proc-ts")

    channel, ts, _ = mock_update_response.call_args[0]
    assert ts == "proc-ts"


@patch("src.update_or_create._get_kb_index")
@patch("src.update_or_create.hitl_register")
@patch("src.update_or_create.update_response")
@patch("src.update_or_create.match")
def test_falls_back_to_thread_ts_when_no_processing_ts(
    mock_match, mock_update_response, mock_hitl_register, mock_get_kb_index
):
    mock_match.return_value = MatchResult(candidates=[_candidate(0.5)])
    mock_get_kb_index.return_value = MagicMock()

    from src.update_or_create import run_update_or_create
    run_update_or_create("C1_1.2", _article(), "C1", "thread-ts")

    channel, ts, _ = mock_update_response.call_args[0]
    assert ts == "thread-ts"


# ---------------------------------------------------------------------------
# execute_create
# ---------------------------------------------------------------------------

@patch("src.update_or_create._get_kb_index")
@patch("src.update_or_create.create_page")
@patch("src.update_or_create.get_store")
@patch("src.update_or_create.update_response")
def test_execute_create_posts_kb_card(
    mock_update_response, mock_get_store, mock_create_page, mock_get_kb_index
):
    mock_create_page.return_value = ("https://confluence.example.com/page/5", "page-5")
    mock_store = MagicMock()
    mock_store.get_page_id.return_value = None
    mock_get_store.return_value = mock_store
    mock_get_kb_index.return_value = MagicMock()

    from src.update_or_create import execute_create
    execute_create("C1_5.0", _article(), "C1", "resp-ts")

    mock_create_page.assert_called_once()
    mock_update_response.assert_called_once()
    payload = mock_update_response.call_args[0][2]
    assert "KB Article Created" in str(payload)


# ---------------------------------------------------------------------------
# execute_cancel
# ---------------------------------------------------------------------------

@patch("src.update_or_create.dm_user")
@patch("src.update_or_create.update_response")
def test_execute_cancel_posts_card_and_dms(mock_update_response, mock_dm_user):
    from src.update_or_create import execute_cancel
    execute_cancel(_article(), "C1", "resp-ts", user_id="U99")

    mock_update_response.assert_called_once()
    payload = mock_update_response.call_args[0][2]
    assert "Cancelled" in str(payload)
    call_args = mock_dm_user.call_args[0]
    assert call_args[0] == "U99"
    assert "cancelled" in call_args[1].lower()


@patch("src.update_or_create.dm_user")
@patch("src.update_or_create.update_response")
def test_execute_cancel_no_dm_when_no_user_id(mock_update_response, mock_dm_user):
    from src.update_or_create import execute_cancel
    execute_cancel(_article(), "C1", "resp-ts", user_id=None)

    mock_update_response.assert_called_once()
    mock_dm_user.assert_not_called()


# ---------------------------------------------------------------------------
# _three_way_merge
# ---------------------------------------------------------------------------

def test_merge_no_human_edits_returns_draft():
    from src.update_or_create import _three_way_merge
    base = _article()
    draft = _article()
    draft.summary = "Updated summary"
    merged = _three_way_merge(base, draft, human_edited=False)
    assert merged.summary == "Updated summary"


def test_merge_human_edits_protects_scalar_fields():
    from src.update_or_create import _three_way_merge
    base = _article()
    draft = _article()
    draft.summary = "Agent updated summary"
    draft.resolution = "Agent updated resolution"
    merged = _three_way_merge(base, draft, human_edited=True)
    # Scalar fields should keep base values
    assert merged.summary == base.summary
    assert merged.resolution == base.resolution


def test_merge_human_edits_unions_list_fields():
    from src.update_or_create import _three_way_merge
    base = _article()
    base.systems_affected = ["auth-service"]
    draft = _article()
    draft.systems_affected = ["auth-service", "cache-service"]
    merged = _three_way_merge(base, draft, human_edited=True)
    assert "auth-service" in merged.systems_affected
    assert "cache-service" in merged.systems_affected


def test_merge_no_base_returns_draft():
    from src.update_or_create import _three_way_merge
    draft = _article()
    merged = _three_way_merge(None, draft, human_edited=True)
    assert merged == draft
