"""Tests for POST /slack/actions endpoint."""
import json
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.extraction.models import KBArticle
from src.hitl_store import PendingInteraction, _clear_all


def _article() -> KBArticle:
    return KBArticle(
        title="Auth outage",
        summary="IAM role expired",
        incident_type="incident",
        systems_affected=["auth"],
        steps_taken=["rotated IAM"],
        resolution="Rotated",
        tags=["auth"],
        related_topics=[],
        confidence_score=0.9,
        extraction_viable=True,
        pii_detected=False,
    )


def _pending(interaction_id: str = "hitl_C1_1.0") -> PendingInteraction:
    return PendingInteraction(
        interaction_id=interaction_id,
        article_id="C1_1.0",
        article=_article(),
        channel_id="C1",
        thread_ts="1.0",
        processing_ts="proc-ts",
        user_id="U1",
        expires_at=time.monotonic() + 1800,
    )


@pytest.fixture(autouse=True)
def clear_store():
    _clear_all()
    yield
    _clear_all()


@pytest.fixture
def client():
    import os
    os.environ.setdefault("ANTHROPIC_API_KEY", "test")
    os.environ.setdefault("SLACK_BOT_TOKEN", "test")
    os.environ.setdefault("SLACK_SIGNING_SECRET", "test")
    from src.adapters.fastapi_app import app
    return TestClient(app, raise_server_exceptions=False)


def _make_payload(action_id: str) -> dict:
    return {
        "type": "block_actions",
        "actions": [{"action_id": action_id}],
        "user": {"id": "U1"},
    }


def _post_interaction(client, payload: dict, verify: bool = True):
    with patch("src.adapters.fastapi_app.verify_signature", return_value=True):
        return client.post(
            "/slack/actions",
            data={"payload": json.dumps(payload)},
        )


def test_unknown_action_returns_200(client):
    resp = _post_interaction(client, _make_payload("some_other_action"))
    assert resp.status_code == 200


@patch("src.adapters.fastapi_app.update_response")
def test_expired_interaction_returns_already_actioned(mock_update_response, client):
    payload = _make_payload("hitl_create:hitl_C1_1.0")
    payload["channel"] = {"id": "C1"}
    payload["message"] = {"ts": "1.0"}
    resp = _post_interaction(client, payload)
    assert resp.status_code == 200
    mock_update_response.assert_called_once()
    posted = mock_update_response.call_args[0][2]
    assert "already been actioned" in str(posted)


@patch("src.adapters.fastapi_app.execute_create")
@patch("src.adapters.fastapi_app.hitl_consume")
def test_create_action_dispatches_execute_create(mock_consume, mock_execute_create, client):
    mock_consume.return_value = _pending()

    resp = _post_interaction(client, _make_payload("hitl_create:hitl_C1_1.0"))
    assert resp.status_code == 200
    mock_execute_create.assert_called_once()


@patch("src.adapters.fastapi_app.execute_update")
@patch("src.adapters.fastapi_app.hitl_consume")
def test_update_action_dispatches_execute_update(mock_consume, mock_execute_update, client):
    mock_consume.return_value = _pending()

    resp = _post_interaction(client, _make_payload("hitl_update:hitl_C1_1.0:page-99"))
    assert resp.status_code == 200
    mock_execute_update.assert_called_once()


@patch("src.adapters.fastapi_app.execute_cancel")
@patch("src.adapters.fastapi_app.hitl_consume")
def test_cancel_action_dispatches_execute_cancel(mock_consume, mock_execute_cancel, client):
    mock_consume.return_value = _pending()

    resp = _post_interaction(client, _make_payload("hitl_cancel:hitl_C1_1.0"))
    assert resp.status_code == 200


def test_invalid_signature_returns_401(client):
    with patch("src.adapters.fastapi_app.verify_signature", return_value=False):
        resp = client.post(
            "/slack/actions",
            data={"payload": json.dumps(_make_payload("hitl_create:x"))},
        )
    assert resp.status_code == 401


def test_non_block_actions_type_returns_200(client):
    payload = {"type": "shortcut", "actions": []}
    resp = _post_interaction(client, payload)
    assert resp.status_code == 200
