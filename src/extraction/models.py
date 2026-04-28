from typing import Literal, Optional
from pydantic import BaseModel, Field

IncidentType = Literal["incident", "qa", "howto", "config", "other"]
Severity = Literal["p1", "p2", "p3", "p4", "unknown"]


class KBArticle(BaseModel):
    title: str
    summary: str
    incident_type: IncidentType
    severity: Optional[Severity] = None
    systems_affected: list[str]
    prerequisites: list[str] = Field(default_factory=list)
    steps_taken: list[str]
    resolution: str
    root_cause: Optional[str] = None
    action_items: list[str] = Field(default_factory=list)
    tags: list[str]
    related_topics: list[str]
    confidence_score: float = Field(ge=0.0, le=1.0)
    extraction_viable: bool
    low_confidence_reason: Optional[str] = None
    pii_detected: bool
    pii_fields: list[str] = Field(default_factory=list)
