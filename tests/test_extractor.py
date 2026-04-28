"""
Unit tests (no API): model validation and tool schema integrity.
Integration tests (require ANTHROPIC_API_KEY): run with `pytest -m integration`.
"""
import pytest
from pydantic import ValidationError

from src.extraction.models import KBArticle
from src.extraction.extractor import EXTRACT_TOOL


# ---------------------------------------------------------------------------
# Model validation — no API key required
# ---------------------------------------------------------------------------

class TestKBArticleModel:
    def _valid(self, **overrides) -> dict:
        base = {
            "title": "Test Article",
            "summary": "A test summary.",
            "incident_type": "incident",
            "severity": "p2",
            "systems_affected": ["api-service"],
            "prerequisites": [],
            "steps_taken": ["step one"],
            "resolution": "Rolled back the deployment.",
            "root_cause": "Missing null check.",
            "action_items": [],
            "tags": ["deployment", "rollback"],
            "related_topics": [],
            "confidence_score": 0.85,
            "extraction_viable": True,
            "low_confidence_reason": None,
            "pii_detected": False,
            "pii_fields": [],
        }
        return {**base, **overrides}

    def test_valid_incident(self):
        article = KBArticle.model_validate(self._valid())
        assert article.incident_type == "incident"
        assert article.extraction_viable is True

    def test_valid_config_type(self):
        article = KBArticle.model_validate(self._valid(
            incident_type="config",
            severity=None,
            root_cause=None,
            prerequisites=["Requires appconfig:StartDeployment IAM permission"],
        ))
        assert article.incident_type == "config"
        assert article.severity is None
        assert article.root_cause is None
        assert len(article.prerequisites) == 1

    def test_valid_howto_type(self):
        article = KBArticle.model_validate(self._valid(
            incident_type="howto",
            severity=None,
            root_cause=None,
            prerequisites=["AWS Secrets Manager access", "Rotation Lambda configured"],
        ))
        assert article.incident_type == "howto"
        assert article.prerequisites == ["AWS Secrets Manager access", "Rotation Lambda configured"]

    def test_not_viable_has_reason(self):
        article = KBArticle.model_validate(self._valid(
            confidence_score=0.31,
            extraction_viable=False,
            low_confidence_reason="Thread too short — 4 messages, no resolution found.",
        ))
        assert article.extraction_viable is False
        assert article.low_confidence_reason is not None

    def test_confidence_score_bounds(self):
        with pytest.raises(ValidationError):
            KBArticle.model_validate(self._valid(confidence_score=1.5))
        with pytest.raises(ValidationError):
            KBArticle.model_validate(self._valid(confidence_score=-0.1))

    def test_invalid_incident_type(self):
        with pytest.raises(ValidationError):
            KBArticle.model_validate(self._valid(incident_type="bug"))

    def test_invalid_severity(self):
        with pytest.raises(ValidationError):
            KBArticle.model_validate(self._valid(severity="critical"))

    def test_pii_detected(self):
        article = KBArticle.model_validate(self._valid(
            pii_detected=True,
            pii_fields=["summary"],
        ))
        assert article.pii_detected is True
        assert "summary" in article.pii_fields


class TestToolSchema:
    def test_tool_has_required_fields(self):
        required = set(EXTRACT_TOOL["input_schema"]["required"])
        expected = {
            "title", "summary", "incident_type", "severity", "systems_affected",
            "prerequisites", "steps_taken", "resolution", "root_cause", "action_items",
            "tags", "related_topics", "confidence_score", "extraction_viable",
            "low_confidence_reason", "pii_detected", "pii_fields",
        }
        assert required == expected

    def test_tool_name(self):
        assert EXTRACT_TOOL["name"] == "extract_kb_article"

    def test_confidence_score_has_bounds(self):
        schema = EXTRACT_TOOL["input_schema"]["properties"]["confidence_score"]
        assert schema["minimum"] == 0.0
        assert schema["maximum"] == 1.0

    def test_incident_type_enum(self):
        enum = EXTRACT_TOOL["input_schema"]["properties"]["incident_type"]["enum"]
        assert set(enum) == {"incident", "qa", "howto", "config", "other"}


# ---------------------------------------------------------------------------
# Integration tests — require ANTHROPIC_API_KEY
# Run: pytest -m integration
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestExtractionIntegration:
    """Each test asserts behavioral outcomes from the prompt, not exact field values."""

    def test_thread_a_incident(self, thread_a):
        from src.extraction.extractor import extract
        article = extract(thread_a)

        assert article.incident_type == "incident"
        assert article.extraction_viable is True
        assert article.confidence_score >= 0.8
        assert article.severity in ("p1", "p2", "p3", "p4", "unknown")
        assert article.root_cause is not None
        assert any("summary-enrichment" in s or "prediction" in s or "connection" in s
                   for s in article.systems_affected + [article.root_cause])
        assert "api-summary" in " ".join(article.systems_affected + article.tags).lower() or \
               "summary" in " ".join(article.tags).lower()

    def test_thread_b_config(self, thread_b):
        from src.extraction.extractor import extract
        article = extract(thread_b)

        # Thread sits at the howto/config boundary — either is acceptable.
        # The key invariant is correct type-conditional field application.
        assert article.incident_type in ("howto", "config")
        assert article.extraction_viable is True
        assert article.root_cause is None
        assert article.severity is None
        assert len(article.prerequisites) > 0
        assert any("appconfig" in p.lower() or "iam" in p.lower() or "permission" in p.lower()
                   for p in article.prerequisites)
        assert any("smart-search" in s.lower() or "appconfig" in s.lower()
                   for s in article.systems_affected + article.tags)

    def test_thread_c_howto(self, thread_c):
        from src.extraction.extractor import extract
        article = extract(thread_c)

        assert article.incident_type == "howto"
        assert article.extraction_viable is True
        assert article.confidence_score >= 0.8
        assert article.root_cause is None
        assert article.severity is None
        assert len(article.prerequisites) > 0
        assert len(article.steps_taken) >= 4

    def test_thread_d_not_viable(self, thread_d):
        from src.extraction.extractor import extract
        article = extract(thread_d)

        assert article.extraction_viable is False
        assert article.confidence_score < 0.4
        assert article.low_confidence_reason is not None
        assert len(article.low_confidence_reason) > 0

    def test_thread_a_pii_detected(self, thread_a):
        from src.extraction.extractor import extract
        article = extract(thread_a)

        assert article.pii_detected is True, (
            "Expected pii_detected=True — thread contains jane.doe@example.com"
        )
        assert len(article.pii_fields) > 0, "Expected at least one field name in pii_fields"
