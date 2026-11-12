"""Prolific sample quote and the panel payload built from it."""

from typing import Literal

from pydantic import BaseModel, Field

PurchaseStatus = Literal[
    "quoted",
    "draft",
    "publishing",
    "active",
    "paused",
    "awaiting_review",
    "completed",
]


class AgeBand(BaseModel):
    """One age quota band."""

    lower: int
    upper: int
    weighting: float


class AudienceFilter(BaseModel):
    """One Prolific filter, with labels the panel can show."""

    filter_id: str
    label: str
    kind: Literal["select", "range"]
    selected_values: list[str] = Field(default_factory=list)
    choice_labels: dict[str, str] = Field(default_factory=dict)
    lower: int | None = None
    upper: int | None = None
    weightings: dict[str, float] = Field(default_factory=dict)
    age_bands: list[AgeBand] = Field(default_factory=list)


class QuotaCell(BaseModel):
    """A planned cell. The count is the share of the sample, not a live fill."""

    labels: list[str]
    places: int


class SamplePurchase(BaseModel):
    """A priced audience. Publishing is a later, confirmed step."""

    provider: Literal["prolific"] = "prolific"
    status: PurchaseStatus = "quoted"
    name: str
    description: str
    sample_size: int
    estimated_minutes: int
    minutes_estimated: bool = False
    reward_cents: int
    reward_per_hour_cents: int
    min_reward_per_hour_cents: int
    currency: str
    participant_pay_cents: int
    total_cost_cents: int
    fees_cents: int | None = None
    tax_cents: int | None = None
    rewards_cents: int | None = None
    available_balance_cents: int | None = None
    shortfall_cents: int | None = None
    eligible_count: int
    eligible_note: str = ""
    workspace_id: str
    prolific_project_id: str | None = None
    study_type: str | None = None
    study_type_note: str = ""
    filters: list[AudienceFilter] = Field(default_factory=list)
    quota_cells: list[QuotaCell] = Field(default_factory=list)
    screenout_reward_cents: int = 0
    screenout_slots: int = 0
    screenout_note: str = ""
    devices: list[str] = Field(default_factory=lambda: ["desktop", "tablet", "mobile"])
    decipher_survey_url: str | None = None
    decipher_ready: bool = False
    prolific_study_id: str | None = None
    prolific_status: str | None = None
    completion_codes: dict[str, str] = Field(default_factory=dict)
    submission_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    launch_blockers: list[str] = Field(default_factory=list)


class QuoteEdit(BaseModel):
    """Panel edits. The server prices them again."""

    sample_size: int = Field(ge=1)
    estimated_minutes: int = Field(ge=1)
    reward_cents: int | None = Field(default=None, ge=1)
    filters: list[AudienceFilter] = Field(default_factory=list)
    study_type: str | None = None
    devices: list[str] = Field(default_factory=list)


class LaunchConfirm(BaseModel):
    """The total the user saw, and an explicit publish confirmation."""

    confirm: bool = False
    total_cost_cents: int


class TransitionRequest(BaseModel):
    """Pause, resume, or stop a published study."""

    action: Literal["PAUSE", "START", "STOP"]
