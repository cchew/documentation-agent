from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field

ScoreLabel = Literal["Strong match", "Possible match"]


class MatchCandidate(BaseModel):
    page_id: str
    title: str
    confluence_url: str | None = None
    score: float = Field(ge=0.0, le=1.0)
    score_label: ScoreLabel
    reason: str


class MatchResult(BaseModel):
    candidates: list[MatchCandidate]

    @computed_field
    @property
    def has_candidates(self) -> bool:
        return any(c.score >= 0.4 for c in self.candidates)

    @computed_field
    @property
    def has_strong_match(self) -> bool:
        return any(c.score >= 0.85 for c in self.candidates)
