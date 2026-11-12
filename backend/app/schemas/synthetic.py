"""Synthetic respondent data: the model's answer profile and the stored report."""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ValidationCheck


class Trait(BaseModel):
    """A hidden respondent attitude that links answers across questions."""

    name: str
    description: str = ""


class TraitLevel(BaseModel):
    """Where a persona sits on one trait, from -1 (low) to 1 (high)."""

    trait: str
    level: float


class Persona(BaseModel):
    """One kind of respondent and the share of completes it should make up."""

    name: str
    share: float
    description: str = ""
    traits: list[TraitLevel] = Field(default_factory=list)


class QuotaTarget(BaseModel):
    """One quota cell tied to a survey question.

    A code cell names the answer code. A range cell names an inclusive numeric range.
    """

    question: str
    label: str = ""
    code: str | None = None
    lower: float | None = None
    upper: float | None = None
    share: float


class SurveyPlan(BaseModel):
    """Personas, traits, and quotas the model proposes for the whole sample."""

    traits: list[Trait] = Field(default_factory=list)
    personas: list[Persona] = Field(default_factory=list)
    quotas: list[QuotaTarget] = Field(default_factory=list)
    sample_size: int | None = None
    notes: list[str] = Field(default_factory=list)


class Weight(BaseModel):
    """A relative weight, or a selection probability for a multi-select row."""

    code: str
    weight: float


class GridRow(BaseModel):
    """Column weights for one grid row."""

    row: str
    weights: list[Weight] = Field(default_factory=list)


class PersonaAnswers(BaseModel):
    """How one persona answers one question."""

    persona: str
    weights: list[Weight] = Field(default_factory=list)
    grid: list[GridRow] = Field(default_factory=list)
    minimum: float | None = None
    maximum: float | None = None
    typical: float | None = None
    verbatims: list[str] = Field(default_factory=list)


class Loading(BaseModel):
    """How a trait moves one answer.

    ``target`` is an answer code for single, multi, rank, and allocation questions,
    a row code for grids, and empty for a number. A positive effect makes that code
    more likely, moves a grid row toward higher column codes, or raises the number.
    """

    trait: str
    target: str = ""
    effect: float


class QuestionProfile(BaseModel):
    """Answer patterns for one question, per persona, plus trait loadings."""

    label: str
    personas: list[PersonaAnswers] = Field(default_factory=list)
    loadings: list[Loading] = Field(default_factory=list)


class ProfileBatch(BaseModel):
    """Structured output for one batch of questions."""

    questions: list[QuestionProfile] = Field(default_factory=list)


class PersonaCount(BaseModel):
    """Completes drawn for one persona."""

    name: str
    description: str = ""
    target_share: float
    completes: int


class QuotaCount(BaseModel):
    """Target and achieved completes for one quota cell."""

    question: str
    label: str
    target: int
    achieved: int


class TraitLink(BaseModel):
    """A trait and the questions it moves."""

    name: str
    description: str = ""
    questions: list[str] = Field(default_factory=list)


class SyntheticReport(BaseModel):
    """What was generated, from which survey, and how it was checked."""

    title: str
    decipher_artifact_id: str
    decipher_version: int
    sample_size: int
    completes: int
    attempts: int
    terminated: int
    seed: int
    personas: list[PersonaCount] = Field(default_factory=list)
    quotas: list[QuotaCount] = Field(default_factory=list)
    traits: list[TraitLink] = Field(default_factory=list)
    variable_count: int = 0
    profiled_questions: int = 0
    question_count: int = 0
    answer_source: Literal["model", "uniform"] = "uniform"
    dataset_id: str | None = None
    dataset_active: bool = False
    export_file_id: str | None = None
    warnings: list[str] = Field(default_factory=list)
    checks: list[ValidationCheck] = Field(default_factory=list)
