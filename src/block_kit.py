"""Builds the Slack Block Kit response message for a KB article creation result."""
import time

from src.doco_agent_core.models import MatchCandidate
from src.extraction.models import KBArticle

_SEVERITY_EMOJI = {"p1": "🔴", "p2": "🟡", "p3": "🔵", "p4": "🟢", "unknown": "⚪"}


def build_kb_response(article: KBArticle, confluence_url: str | None = None) -> dict:
    title_text = f"📄 *{article.title}*"
    type_badge = article.incident_type.upper()
    score_pct = int(article.confidence_score * 100)

    tag_line = "🏷️  " + " • ".join(article.tags[:6]) if article.tags else ""

    lines = [f"*Type:* {type_badge}   *Confidence:* {score_pct}%"]

    if article.severity:
        sev_emoji = _SEVERITY_EMOJI.get(article.severity, "⚪")
        lines.append(f"*Severity:* {sev_emoji} {article.severity.upper()}")

    if tag_line:
        lines.append(tag_line)

    if article.pii_detected:
        fields_str = ", ".join(article.pii_fields)
        lines.append(f"⚠️  *PII detected in:* {fields_str} — review before sharing")

    body_text = "\n".join(lines)

    # P1 incidents get a red (danger) button; everything else gets primary
    button_style = "danger" if article.severity == "p1" else "primary"

    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": "✅ *KB Article Created*"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": title_text}},
        {"type": "section", "text": {"type": "mrkdwn", "text": body_text}},
        {"type": "divider"},
    ]

    if confluence_url:
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View in Confluence →"},
                    "url": confluence_url,
                    "style": button_style,
                }
            ],
        })

    ts = int(time.time())
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": (
                    f"🤖 Documentation Agent  •  "
                    f"<!date^{ts}^{{date_short_pretty}} at {{time}}|just now>"
                ),
            }
        ],
    })

    return {"blocks": blocks}


def build_not_viable_response(article: KBArticle) -> dict:
    reason = article.low_confidence_reason or "Thread did not contain enough information."
    return {
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": "⚠️ *KB Article Not Created*"}},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Confidence score too low ({int(article.confidence_score * 100)}%).\n_{reason}_",
                },
            },
        ]
    }


def build_match_candidates_card(candidates: list[MatchCandidate]) -> dict:
    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": "🔍 *Similar articles found*"}},
    ]

    for candidate in candidates:
        if candidate.confluence_url:
            title_part = f"<{candidate.confluence_url}|{candidate.title}>"
        else:
            title_part = candidate.title
        text = f"*{candidate.score_label}:* {title_part}\n_{candidate.reason}_"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})

    blocks.append({"type": "divider"})
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "_A new article will be created._"}})

    return {"blocks": blocks}


def build_match_confirmation_card(
    candidates: list[MatchCandidate],
    interaction_id: str,
    has_strong_match: bool,
) -> dict:
    """Interactive HITL card — one button per candidate + Create new + Cancel.

    action_id encoding: hitl_update:{interaction_id}:{page_id}
                        hitl_create:{interaction_id}
                        hitl_cancel:{interaction_id}
    """
    blocks: list[dict] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "🔍 *Similar articles found — choose an action*",
            },
        },
    ]

    for candidate in candidates:
        if candidate.confluence_url:
            title_part = f"<{candidate.confluence_url}|{candidate.title}>"
        else:
            title_part = candidate.title
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{candidate.score_label}:* {title_part}\n_{candidate.reason}_",
            },
        })

    blocks.append({"type": "divider"})

    # One button per candidate for updates, plus Create new + Cancel
    action_elements: list[dict] = []
    for candidate in candidates:
        label = candidate.title[:48] + "…" if len(candidate.title) > 48 else candidate.title
        btn: dict = {
            "type": "button",
            "text": {"type": "plain_text", "text": f"Update: {label}"},
            "action_id": f"hitl_update:{interaction_id}:{candidate.page_id}",
        }
        if candidate.score >= 0.85:
            btn["style"] = "primary"
        action_elements.append(btn)

    create_btn: dict = {
        "type": "button",
        "text": {"type": "plain_text", "text": "Create new article"},
        "action_id": f"hitl_create:{interaction_id}",
    }
    if not has_strong_match:
        create_btn["style"] = "primary"
    action_elements.append(create_btn)

    action_elements.append({
        "type": "button",
        "text": {"type": "plain_text", "text": "Cancel"},
        "action_id": f"hitl_cancel:{interaction_id}",
        "style": "danger",
    })

    blocks.append({"type": "actions", "elements": action_elements})

    return {"blocks": blocks}


def build_error_response(message: str) -> dict:
    return {
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"❌ *KB Article Creation Failed*\n_{message}_"},
            }
        ]
    }
