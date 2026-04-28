"""Builds the Slack Block Kit response message for a KB article creation result."""
import time

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


def build_error_response(message: str) -> dict:
    return {
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"❌ *KB Article Creation Failed*\n_{message}_"},
            }
        ]
    }
