import pytest

from src.block_kit import build_match_confirmation_card
from src.doco_agent_core.models import MatchCandidate


def _candidate(page_id: str, score: float, title: str = "Auth Failure") -> MatchCandidate:
    label = "Strong match" if score >= 0.85 else "Possible match"
    return MatchCandidate(
        page_id=page_id,
        title=title,
        confluence_url=f"https://confluence.example.com/pages/{page_id}",
        score=score,
        score_label=label,
        reason="Similar content",
    )


def test_card_contains_all_candidate_titles():
    candidates = [
        _candidate("p1", 0.9, "Auth Failure"),
        _candidate("p2", 0.6, "IAM Expiry"),
    ]
    card = build_match_confirmation_card(candidates, "hitl_C1_1.0", has_strong_match=True)
    block_text = str(card)
    assert "Auth Failure" in block_text
    assert "IAM Expiry" in block_text


def test_card_has_update_buttons_per_candidate():
    candidates = [_candidate("p1", 0.9), _candidate("p2", 0.5)]
    card = build_match_confirmation_card(candidates, "hitl_C1_1.0", has_strong_match=True)
    action_ids = _collect_action_ids(card)
    assert "hitl_update:hitl_C1_1.0:p1" in action_ids
    assert "hitl_update:hitl_C1_1.0:p2" in action_ids


def test_card_has_create_and_cancel_buttons():
    candidates = [_candidate("p1", 0.5)]
    card = build_match_confirmation_card(candidates, "hitl_X", has_strong_match=False)
    action_ids = _collect_action_ids(card)
    assert "hitl_create:hitl_X" in action_ids
    assert "hitl_cancel:hitl_X" in action_ids


def test_strong_match_sets_primary_on_update_buttons():
    candidates = [_candidate("p1", 0.9)]
    card = build_match_confirmation_card(candidates, "hitl_X", has_strong_match=True)
    update_btn = _find_button(card, "hitl_update:hitl_X:p1")
    assert update_btn is not None
    assert update_btn.get("style") == "primary"


def test_no_strong_match_sets_primary_on_create_button():
    candidates = [_candidate("p1", 0.5)]
    card = build_match_confirmation_card(candidates, "hitl_X", has_strong_match=False)
    create_btn = _find_button(card, "hitl_create:hitl_X")
    assert create_btn is not None
    assert create_btn.get("style") == "primary"


def test_cancel_button_always_danger():
    candidates = [_candidate("p1", 0.9)]
    card = build_match_confirmation_card(candidates, "hitl_X", has_strong_match=True)
    cancel_btn = _find_button(card, "hitl_cancel:hitl_X")
    assert cancel_btn is not None
    assert cancel_btn.get("style") == "danger"


def test_long_title_truncated_in_button_label():
    long_title = "A" * 60
    candidates = [_candidate("p1", 0.9, long_title)]
    card = build_match_confirmation_card(candidates, "hitl_X", has_strong_match=True)
    update_btn = _find_button(card, "hitl_update:hitl_X:p1")
    assert update_btn is not None
    label = update_btn["text"]["text"]
    assert len(label) <= 60  # "Update: " + up to 48 chars + "…"


def test_card_has_actions_block():
    candidates = [_candidate("p1", 0.5)]
    card = build_match_confirmation_card(candidates, "hitl_X", has_strong_match=False)
    types = [b["type"] for b in card["blocks"]]
    assert "actions" in types


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_action_ids(card: dict) -> list[str]:
    ids = []
    for block in card.get("blocks", []):
        if block.get("type") == "actions":
            for el in block.get("elements", []):
                ids.append(el.get("action_id", ""))
    return ids


def _find_button(card: dict, action_id: str) -> dict | None:
    for block in card.get("blocks", []):
        if block.get("type") == "actions":
            for el in block.get("elements", []):
                if el.get("action_id") == action_id:
                    return el
    return None
