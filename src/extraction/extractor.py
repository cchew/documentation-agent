import anthropic
from .models import KBArticle
from .prompts import SYSTEM_PROMPT

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2048

EXTRACT_TOOL = {
    "name": "extract_kb_article",
    "description": "Extract a structured KB article from a Slack thread conversation.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Concise, descriptive title for the KB article."
            },
            "summary": {
                "type": "string",
                "description": "3-5 sentence standalone summary: what happened/was asked, the resolution/answer, and any key caveats."
            },
            "incident_type": {
                "type": "string",
                "enum": ["incident", "qa", "howto", "config", "other"],
                "description": "Thread classification."
            },
            "severity": {
                "type": ["string", "null"],
                "enum": ["p1", "p2", "p3", "p4", "unknown", None],
                "description": "Incident severity. Populate only for incident type; null otherwise."
            },
            "systems_affected": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Systems, services, or tools involved."
            },
            "prerequisites": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Preconditions required before following this procedure. Populate for howto and config types only."
            },
            "steps_taken": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Ordered steps taken to diagnose/resolve (incident) or follow the procedure (howto/config)."
            },
            "resolution": {
                "type": "string",
                "description": "What resolved the issue or what the final answer was."
            },
            "root_cause": {
                "type": ["string", "null"],
                "description": "Root cause of the incident. Populate only for incident type; null otherwise."
            },
            "action_items": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Follow-up tasks identified in the thread (PRs to merge, docs to write, tickets to file)."
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "4-8 lowercase kebab-case tags covering systems, thread type, and key concepts."
            },
            "related_topics": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Related KB topics or processes this article links to."
            },
            "confidence_score": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Extraction confidence using the rubric: 0.8-1.0 clear, 0.6-0.79 partial, 0.4-0.59 weak, 0.0-0.39 not viable."
            },
            "extraction_viable": {
                "type": "boolean",
                "description": "False if confidence_score < 0.4. Gate used by the backend to decide whether to create a Confluence page."
            },
            "low_confidence_reason": {
                "type": ["string", "null"],
                "description": "Required when extraction_viable is false. Explains why (e.g. 'Thread too short — 4 messages, no resolution found')."
            },
            "pii_detected": {
                "type": "boolean",
                "description": "True if PII was found in the extracted fields (not the raw thread)."
            },
            "pii_fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Field names where PII was detected (e.g. ['summary', 'root_cause'])."
            }
        },
        "required": [
            "title", "summary", "incident_type", "severity", "systems_affected",
            "prerequisites", "steps_taken", "resolution", "root_cause", "action_items",
            "tags", "related_topics", "confidence_score", "extraction_viable",
            "low_confidence_reason", "pii_detected", "pii_fields"
        ]
    }
}


def extract(thread_text: str, client: anthropic.Anthropic | None = None) -> KBArticle:
    if client is None:
        client = anthropic.Anthropic()

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[EXTRACT_TOOL],
        tool_choice={"type": "tool", "name": "extract_kb_article"},
        messages=[
            {
                "role": "user",
                "content": f"Extract a KB article from this Slack thread:\n\n{thread_text}"
            }
        ]
    )

    tool_blocks = [b for b in response.content if b.type == "tool_use"]
    if not tool_blocks:
        raise ValueError("Claude did not invoke the extraction tool — response malformed.")
    return KBArticle.model_validate(tool_blocks[0].input)
