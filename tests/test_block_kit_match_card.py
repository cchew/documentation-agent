from __future__ import annotations

from src.block_kit import build_match_candidates_card
from src.doco_agent_core.models import MatchCandidate


def _make_candidate(
    title: str,
    score_label: str = "Strong match",
    reason: str = "Highly relevant content.",
    confluence_url: str | None = None,
    score: float = 0.9,
    page_id: str = "123",
) -> MatchCandidate:
    return MatchCandidate(
        page_id=page_id,
        title=title,
        confluence_url=confluence_url,
        score=score,
        score_label=score_label,  # type: ignore[arg-type]
        reason=reason,
    )


def test_match_card_with_candidates() -> None:
    candidates = [
        _make_candidate(
            title="Incident Response Guide",
            score_label="Strong match",
            reason="Covers the exact same system failure.",
            confluence_url="https://confluence.example.com/page/1",
            page_id="1",
            score=0.92,
        ),
        _make_candidate(
            title="General Troubleshooting",
            score_label="Possible match",
            reason="Broadly related troubleshooting steps.",
            confluence_url=None,
            page_id="2",
            score=0.55,
        ),
    ]

    result = build_match_candidates_card(candidates)
    blocks = result["blocks"]

    # Header block
    assert "Similar articles found" in blocks[0]["text"]["text"]

    # First candidate block — linked title
    first_candidate_text = blocks[1]["text"]["text"]
    assert "Strong match" in first_candidate_text
    assert "<https://confluence.example.com/page/1|Incident Response Guide>" in first_candidate_text

    # Second candidate block — plain title (no link)
    second_candidate_text = blocks[2]["text"]["text"]
    assert "Possible match" in second_candidate_text
    assert "General Troubleshooting" in second_candidate_text
    assert "<" not in second_candidate_text or "|" not in second_candidate_text

    # Footer
    assert "A new article will be created" in blocks[-1]["text"]["text"]

    # No actions blocks
    assert all(b["type"] != "actions" for b in blocks)


def test_match_card_empty_candidates() -> None:
    result = build_match_candidates_card([])
    blocks = result["blocks"]

    # Header present
    assert any("Similar articles found" in b.get("text", {}).get("text", "") for b in blocks)

    # Footer present
    assert any("A new article will be created" in b.get("text", {}).get("text", "") for b in blocks)

    # Divider present
    assert any(b["type"] == "divider" for b in blocks)

    # No candidate sections (only header + divider + footer = 3 blocks)
    assert len(blocks) == 3
