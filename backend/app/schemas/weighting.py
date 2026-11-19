"""Weighting plans: census targets with references, and the weight built from them."""

from typing import Literal

from pydantic import BaseModel, Field


class TargetSource(BaseModel):
    """A published figure a target was taken from."""

    id: str
    title: str
    url: str
    publisher: str = ""
    year: str = ""
    note: str = ""
    # Reason: only a URL the web search actually returned counts as verified.
    verified: bool = False


class TargetCategory(BaseModel):
    """One weighting cell: the answer codes it covers and its target share."""

    label: str
    codes: list[int | float] = Field(default_factory=list)
    sample_share: float | None = None
    target_share: float | None = None
    origin: Literal["census", "user", "sample"] = "user"
    source_ids: list[str] = Field(default_factory=list)
    note: str = ""


class WeightingDimension(BaseModel):
    """A variable the weight balances, such as age band or region."""

    variable: str
    label: str = ""
    categories: list[TargetCategory] = Field(default_factory=list)
    note: str = ""


class WeightingSettings(BaseModel):
    """Raking limits. Weights are capped relative to a mean of 1."""

    min_weight: float = 0.3
    max_weight: float = 3.0
    max_iterations: int = 200
    tolerance: float = 1e-6


class AchievedShare(BaseModel):
    """Target against the weighted result for one category."""

    variable: str
    label: str
    sample_share: float
    target_share: float
    weighted_share: float


class WeightResult(BaseModel):
    """What the built weight did to the sample."""

    weight_variable: str
    dataset_id: str
    respondents: int
    converged: bool
    iterations: int
    efficiency: float
    effective_base: float
    design_effect: float
    min_weight: float
    max_weight: float
    capped: int = 0
    achieved: list[AchievedShare] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class WeightingPlan(BaseModel):
    """Stored as the ``weighting`` artifact."""

    population: str = ""
    dataset_id: str | None = None
    dimensions: list[WeightingDimension] = Field(default_factory=list)
    sources: list[TargetSource] = Field(default_factory=list)
    settings: WeightingSettings = Field(default_factory=WeightingSettings)
    research_note: str = ""
    status: Literal["proposed", "built"] = "proposed"
    result: WeightResult | None = None
