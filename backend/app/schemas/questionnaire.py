"""Questionnaire document schema."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.expression import Expr

QuestionType = Literal[
    "single_select",
    "multi_select",
    "rating",
    "numeric",
    "text",
    "matrix",
    "rank",
    "allocation",
    "date",
    "grid",
    "loop",
    "screener",
    "terminate",
    "display",
]


class Option(BaseModel):
    """One response option."""

    code: int | str
    label: str
    exclusive: bool = False
    open_text: bool = False
    terminate: bool = False
    anchor: bool = False


class RoutingRule(BaseModel):
    """A conditional jump. ``go_to`` is a question id, END, or TERMINATE."""

    when: Expr | None = None
    go_to: str


class ReportingHint(BaseModel):
    """Suggested statistics. These do not compute numbers."""

    stats: list[str] = Field(default_factory=list)


class Question(BaseModel):
    """One instrument item."""

    id: str
    type: QuestionType
    text: str
    instruction: str | None = None
    programmer_notes: list[str] = Field(default_factory=list)
    options: list[Option] = Field(default_factory=list)
    required: bool = True
    display_if: Expr | None = None
    routing: list[RoutingRule] = Field(default_factory=list)
    randomize_options: bool = False
    exclusive_codes: list[int | str] = Field(default_factory=list)
    variable_names: list[str] = Field(default_factory=list)
    reporting: ReportingHint = Field(default_factory=ReportingHint)
    notes: list[str] = Field(default_factory=list)
    matrix_items: list[str] = Field(default_factory=list)
    unsupported: bool = False


class Objective(BaseModel):
    """A research objective and the questions that measure it."""

    id: str
    description: str
    question_ids: list[str] = Field(default_factory=list)


class Module(BaseModel):
    """A named block of question ids."""

    id: str
    title: str
    question_ids: list[str] = Field(default_factory=list)


class Questionnaire(BaseModel):
    """Canonical questionnaire document."""

    id: str
    title: str
    objectives: list[Objective] = Field(default_factory=list)
    modules: list[Module] = Field(default_factory=list)
    questions: list[Question]
    sample_notes: list[str] = Field(default_factory=list)
    programming_notes: list[str] = Field(default_factory=list)
    estimated_minutes: float | None = None
    estimated_minutes_note: str = "Heuristic length only. This is not a verified timing study."
    schema_version: str = "questionnaire/1"


class FlowIssue(BaseModel):
    """One routing or structure problem."""

    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    question_id: str | None = None


class FlowReport(BaseModel):
    """Result of the flow-graph validator."""

    status: Literal["passed", "passed_with_warnings", "failed"]
    issues: list[FlowIssue] = Field(default_factory=list)
    reachable: list[str] = Field(default_factory=list)
    unreachable: list[str] = Field(default_factory=list)


class StudyBrief(BaseModel):
    """Text extracted from a statement of work."""

    source_name: str
    text: str
    objectives: list[str] = Field(default_factory=list)
    audience: str | None = None
    method_notes: list[str] = Field(default_factory=list)


class RespondentPreview(BaseModel):
    """Questions a respondent would see for one answer path."""

    path: list[str]
    terminated: bool = False
    answers: dict[str, Any] = Field(default_factory=dict)
