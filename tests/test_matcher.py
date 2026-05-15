from __future__ import annotations

import pytest

from src.doco_agent_core.kb_index import KBIndex, KBIndexEntry
from src.doco_agent_core.matcher import match, score_label
from src.extraction.models import KBArticle


def _make_article(
    title: str = "Test Article",
    summary: str = "A test summary.",
    incident_type: str = "incident",
    systems_affected: list[str] | None = None,
    steps_taken: list[str] | None = None,
) -> KBArticle:
    return KBArticle(
        title=title,
        summary=summary,
        incident_type=incident_type,
        systems_affected=systems_affected or ["system-a"],
        steps_taken=steps_taken or ["Step 1.", "Step 2."],
        resolution="Resolved.",
        tags=[],
        related_topics=[],
        confidence_score=0.9,
        extraction_viable=True,
        pii_detected=False,
    )


def _make_entry(page_id: str, title: str = "Existing Article") -> KBIndexEntry:
    return KBIndexEntry(
        page_id=page_id,
        space_key="SPACE",
        title=title,
        incident_type="incident",
        systems_affected=["system-a"],
    )


def test_no_candidates_below_threshold(tmp_path: pytest.TempPathFactory) -> None:
    kb_index = KBIndex(db_path=tmp_path / "kb.db")

    existing = _make_entry("page-001", title="Unrelated database migration procedure")
    kb_index.save(
        existing,
        "Database migration schema upgrade rollback procedure for postgres version bump.",
    )

    article = _make_article(
        title="Network firewall timeout on port 443",
        summary="SSL handshake failed due to firewall misconfiguration.",
        steps_taken=["Checked firewall rules.", "Updated security group ingress."],
    )

    result = match(article, "C001", "111.222", kb_index)
    assert result.has_candidates is False


def test_semantic_match_found(tmp_path: pytest.TempPathFactory) -> None:
    kb_index = KBIndex(db_path=tmp_path / "kb.db")

    existing = KBIndexEntry(
        page_id="page-002",
        space_key="SPACE",
        title="API service memory leak causing OOM crashes",
        incident_type="incident",
        systems_affected=["system-a"],
        confluence_url="https://example.atlassian.net/wiki/spaces/SPACE/pages/page-002",
    )
    kb_index.save(
        existing,
        "API service memory leak causing OOM crashes. Service ran out of memory and crashed. "
        "Identified leak with heap dump. Deployed patched version. Restarted pods.",
    )

    article = _make_article(
        title="API service OOM crash investigation",
        summary="Service crashed with out-of-memory error on production.",
        steps_taken=["Collected heap dump.", "Identified memory leak.", "Deployed fix."],
    )

    result = match(article, "C001", "222.333", kb_index)
    assert result.has_candidates is True
    assert result.candidates[0].score > 0.4
    assert result.candidates[0].confluence_url == "https://example.atlassian.net/wiki/spaces/SPACE/pages/page-002"


def test_exact_rerun_detected(tmp_path: pytest.TempPathFactory) -> None:
    kb_index = KBIndex(db_path=tmp_path / "kb.db")

    channel_id = "C001"
    thread_ts = "333.444"
    article_id = f"{channel_id}_{thread_ts}"

    existing = _make_entry(article_id, title="Previously Published Article")
    kb_index.save(existing, "Some previously indexed content.")

    article = _make_article(title="Previously Published Article")
    result = match(article, channel_id, thread_ts, kb_index)

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.score == 1.0
    assert candidate.reason.startswith("Re-run")
    assert candidate.page_id == article_id


def test_strong_match_label() -> None:
    assert score_label(0.85) == "Strong match"
    assert score_label(0.95) == "Strong match"
    assert score_label(1.0) == "Strong match"


def test_possible_match_label() -> None:
    assert score_label(0.5) == "Possible match"
    assert score_label(0.4) == "Possible match"
    assert score_label(0.84) == "Possible match"
