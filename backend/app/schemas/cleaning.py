"""Fraud-recommendation schema. Counts are computed, not written by a model."""

from typing import Literal

from pydantic import BaseModel, Field

Disposition = Literal["keep", "review", "remove"]
VerbatimLabel = Literal["substantive", "off_topic", "low_effort", "unclear"]


class CleaningRule(BaseModel):
    """One documented check and whether this dataset could run it."""

    id: str
    label: str
    definition: str
    severity: Literal["hard", "soft"]
    ran: bool = True
    skip_reason: str = ""


class RespondentFlag(BaseModel):
    """One rule that fired for one respondent."""

    rule_id: str
    detail: str


class RespondentDisposition(BaseModel):
    """Keep, review, or remove, with the rules behind that choice."""

    source_row_id: int
    respondent_id: str
    disposition: Disposition
    rule_ids: list[str] = Field(default_factory=list)
    flags: list[RespondentFlag] = Field(default_factory=list)


class OpenEndFinding(BaseModel):
    """One open-end exception. The preview is truncated."""

    source_row_id: int
    respondent_id: str
    variable: str
    text_preview: str = ""
    rule_id: str
    detail: str
    model_label: str | None = None


class VerbatimJudgement(BaseModel):
    """A model label for one surrogate id. It is not a count."""

    surrogate_id: str
    label: VerbatimLabel
    note: str = ""


class CleaningSummary(BaseModel):
    """Unweighted disposition counts. Weighted shares are reported beside them."""

    row_count: int
    keep_n: int
    review_n: int
    remove_n: int
    weighted_remove_share: float | None = None
    weighted_review_share: float | None = None
    weight_variable: str | None = None
    skipped: list[str] = Field(default_factory=list)
    rule_counts: dict[str, int] = Field(default_factory=dict)
    semantic_review: str = "Semantic review was not needed."


class CleaningReport(BaseModel):
    """The recommendation for one dataset version."""

    dataset_id: str
    source_sha256: str = ""
    rules: list[CleaningRule]
    respondents: list[RespondentDisposition]
    open_ends: list[OpenEndFinding] = Field(default_factory=list)
    summary: CleaningSummary
