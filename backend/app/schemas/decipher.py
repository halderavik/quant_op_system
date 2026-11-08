"""Decipher survey artifact produced from a questionnaire."""

from typing import Literal

from pydantic import BaseModel, Field


class Punch(BaseModel):
    """One questionnaire code and the Decipher row or column label that stores it."""

    code: str
    label: str
    row_label: str


class CoverageItem(BaseModel):
    """How one question was programmed."""

    question_id: str
    label: str
    element: str
    status: Literal["programmed", "partial"]
    warnings: list[str] = Field(default_factory=list)
    punches: list[Punch] = Field(default_factory=list)


class DecipherProgram(BaseModel):
    """Importable survey XML plus the coverage report."""

    title: str
    xml: str
    items: list[CoverageItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    validation_status: Literal["passed", "passed_with_warnings", "failed"]
    issues: list[str] = Field(default_factory=list)
    launch: Literal["not_configured"] = "not_configured"
    file_id: str | None = None
    questionnaire_artifact_id: str | None = None
    questionnaire_version: int | None = None
