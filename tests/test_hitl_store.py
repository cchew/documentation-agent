import time
from unittest.mock import patch

import pytest

from src.hitl_store import (
    PendingInteraction,
    _clear_all,
    consume,
    get,
    pending_count,
    register,
)
from src.extraction.models import KBArticle


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


@pytest.fixture(autouse=True)
def clear_store():
    _clear_all()
    yield
    _clear_all()


def test_register_and_consume():
    register("iid1", "C1_1.0", _article(), "C1", "1.0", "proc-ts", "U1")
    assert pending_count() == 1
    entry = consume("iid1")
    assert entry is not None
    assert entry.interaction_id == "iid1"
    assert entry.user_id == "U1"
    assert pending_count() == 0


def test_consume_returns_none_for_unknown():
    assert consume("no-such-id") is None


def test_consume_idempotent():
    register("iid2", "C1_2.0", _article(), "C1", "2.0", None, None)
    assert consume("iid2") is not None
    assert consume("iid2") is None  # already consumed


def test_get_does_not_remove():
    register("iid3", "C1_3.0", _article(), "C1", "3.0", None, None)
    entry = get("iid3")
    assert entry is not None
    assert pending_count() == 1  # still there
    assert consume("iid3") is not None


def test_expired_entry_returns_none():
    with patch("src.hitl_store.TIMEOUT_SECONDS", -1):
        register("iid4", "C1_4.0", _article(), "C1", "4.0", None, None)
    # expires_at is in the past; consume should return None
    result = consume("iid4")
    assert result is None


def test_multiple_independent_registrations():
    register("a", "C1_a", _article(), "C1", "a", None, None)
    register("b", "C1_b", _article(), "C1", "b", None, None)
    assert pending_count() == 2
    consume("a")
    assert pending_count() == 1
