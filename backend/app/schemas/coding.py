"""Open-end codeframe, assignment, and frequency schemas."""

from typing import Literal

from pydantic import BaseModel, Field

Sentiment = Literal["positive", "negative", "neutral", "mixed", "unclear"]


class SentimentSpec(BaseModel):
    """Documented sentiment labels for a whole response."""

    labels: list[str] = Field(
        default_factory=lambda: ["positive", "negative", "neutral", "mixed", "unclear"]
    )
    unit: str = "whole_response"


class CodeNode(BaseModel):
    """One code. ``value`` is the numeric punch written to the coded-data sheet."""

    id: str
    label: str
    value: int | None = None
    parent_id: str | None = None
    definition: str = ""
    include_examples: list[str] = Field(default_factory=list)
    exclude_examples: list[str] = Field(default_factory=list)


class NetNode(BaseModel):
    """A respondent-level union of child codes."""

    id: str
    label: str
    child_ids: list[str]


class Codeframe(BaseModel):
    """Approved coding frame. Assignments may use only these code ids."""

    codeframe_id: str
    version: int = 1
    response_variable: str
    respondent_id_variable: str
    weight_variable: str | None = None
    allow_multiple_codes: bool = True
    codes: list[CodeNode]
    nets: list[NetNode] = Field(default_factory=list)
    sentiment: SentimentSpec = Field(default_factory=SentimentSpec)
    placeholders: list[str] = Field(default_factory=lambda: ["", "na", "n/a", "none", "99"])


class HumanOverride(BaseModel):
    """Reviewer decision kept separate from the model assignment."""

    code_ids: list[str]
    sentiment: Sentiment | None = None
    note: str | None = None


class CodingAssignment(BaseModel):
    """One response row. Final codes prefer the human override."""

    respondent_id: str
    source_row_id: int
    response_text: str = ""
    assigned_code_ids: list[str] = Field(default_factory=list)
    sentiment: Sentiment | None = None
    evidence: str | None = None
    review_required: bool = False
    review_reason: str | None = None
    model_version: str | None = None
    codeframe_version: int = 1
    human_overrides: HumanOverride | None = None
    substantive: bool = True


class CodeFrequency(BaseModel):
    """Respondent-level frequency for one code or net."""

    id: str
    label: str
    kind: Literal["code", "net", "bucket"]
    unweighted_respondents: int
    weighted_respondents: float
    base_unweighted: int
    base_weighted: float
    pct_of_respondents: float | None
    unweighted_mentions: int | None = None
    weighted_mentions: float | None = None


class CodingReport(BaseModel):
    """Deterministic frequencies and sentiment distribution."""

    frequencies: list[CodeFrequency]
    sentiment_counts: dict[str, int]
    substantive_n: int
    nonsubstantive_n: int
    warnings: list[str] = Field(default_factory=list)
