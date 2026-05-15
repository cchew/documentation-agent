from __future__ import annotations

from src.doco_agent_core.kb_index import KBIndex
from src.doco_agent_core.models import MatchCandidate, MatchResult, ScoreLabel
from src.extraction.models import KBArticle

AUTO_CREATE_BELOW = 0.4
CONFIRM_BAND_HIGH = 0.85
TOP_K_CANDIDATES = 3
SEARCH_TOP_K = 5


def score_label(score: float) -> ScoreLabel:
    if score >= CONFIRM_BAND_HIGH:
        return "Strong match"
    return "Possible match"


def build_embed_text(article: KBArticle) -> str:
    return f"{article.title}. {article.summary}. {' '.join(article.steps_taken)}"


def match(
    article: KBArticle,
    channel_id: str,
    thread_ts: str,
    kb_index: KBIndex,
    space_key: str | None = None,
) -> MatchResult:
    article_id = f"{channel_id}_{thread_ts}"

    existing = kb_index.get(article_id)
    if existing is not None:
        candidate = MatchCandidate(
            page_id=existing.page_id,
            title=existing.title,
            confluence_url=None,
            score=1.0,
            score_label=score_label(1.0),
            reason="Re-run: this thread was already published.",
        )
        return MatchResult(candidates=[candidate])

    embed_text = build_embed_text(article)
    results = kb_index.search(embed_text, top_k=SEARCH_TOP_K, space_key=space_key)

    candidates: list[MatchCandidate] = []
    for entry, score in results:
        if entry.page_id == article_id:
            continue
        if score < AUTO_CREATE_BELOW:
            continue
        candidates.append(
            MatchCandidate(
                page_id=entry.page_id,
                title=entry.title,
                confluence_url=entry.confluence_url,
                score=score,
                score_label=score_label(score),
                reason="Similar content",
            )
        )
        if len(candidates) >= TOP_K_CANDIDATES:
            break

    return MatchResult(candidates=candidates)
