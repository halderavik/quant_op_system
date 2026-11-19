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


class RowCondition(BaseModel):
    """Show only the rows answered (or not answered) at an earlier question with the same codes."""

    source: str
    # "positive" keeps the rows given a number above zero at a numeric source question.
    mode: Literal["selected", "not_selected", "positive"] = "selected"
    # For a grid source: the scale code a row must have, such as 1 for "Yes" (qAID[row].c1).
    column: int | str | None = None


class OptionCondition(BaseModel):
    """Show one option or row only when a condition holds, such as a country-specific brand."""

    code: int | str
    when: Expr


class TerminateRule(BaseModel):
    """One screen-out. ``immediately`` ends the interview at once; otherwise it waits for the flags."""

    when: Expr
    immediately: bool = False
    label: str = ""


class AutoFill(BaseModel):
    """Answer the question in code ("autopunch 0 and do not show") when ``when`` holds, or always."""

    code: int | str
    when: Expr | None = None


class Pipe(BaseModel):
    """Text in the wording replaced by an earlier answer, such as [INSERT S11]."""

    placeholder: str
    source: str


class Validation(BaseModel):
    """An error shown when ``error_when`` holds ("C2 cannot exceed C1")."""

    error_when: Expr
    message: str


class ProgrammingSpec(BaseModel):
    """How a question is programmed, worked out from its written instructions.

    Every field is optional; unset means the Decipher default. ``unresolved`` keeps
    instructions the structure cannot express, so the programmer sees them.
    """

    hidden: bool = False
    min_value: float | None = None
    max_value: float | None = None
    total: float | None = None
    min_chars: int | None = None
    min_choices: int | None = None
    max_choices: int | None = None
    noanswer_codes: list[int | str] = Field(default_factory=list)
    single_line: bool = False
    row_condition: RowCondition | None = None
    option_conditions: list[OptionCondition] = Field(default_factory=list)
    randomize_columns: bool = False
    # A grid where each row takes several answers ("select all that apply" per row).
    multiple: bool = False
    keep_together: list[list[int | str]] = Field(default_factory=list)
    same_order_as: str | None = None
    # "LIST ALPHABETICALLY": answers sorted A-Z for each respondent; anchored ones stay put.
    sort_alphabetically: bool = False
    # Images or other stimulus shown with the question: file names, or what the file describes.
    images: list[str] = Field(default_factory=list)
    terminate_when: Expr | None = None
    terminate_immediately: bool = False
    # More screen-outs on this question, each with its own timing (under 18 now, 55+ as a flag).
    terminate_rules: list[TerminateRule] = Field(default_factory=list)
    autofill: AutoFill | None = None
    pipes: list[Pipe] = Field(default_factory=list)
    validations: list[Validation] = Field(default_factory=list)
    # Codes that get a one-time prompt before they are accepted ("Prefer not to answer":
    # "Sorry! We need your exact age..."). The respondent can keep the answer on the second try.
    confirm_codes: list[int | str] = Field(default_factory=list)
    confirm_message: str = ""
    # Number of separate entry boxes for a text or number question with no listed rows.
    boxes: int | None = None
    dropdown: bool = False
    unresolved: list[str] = Field(default_factory=list)


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
    programming: ProgrammingSpec | None = None
    # False when the file gives no punch codes and they were numbered in order on import.
    codes_from_file: bool | None = None
    # The part of the uploaded file this question was read from, for side-by-side review.
    source_excerpt: str | None = None


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


class DerivedValue(BaseModel):
    """One value of a derived variable and when a respondent gets it."""

    code: int | str
    label: str
    # None when the value is assigned rather than computed (least fill, random, panel).
    when: Expr | None = None
    # The file marks this group TERMINATE (an age band outside the target, for example).
    terminate: bool = False


class Computation(BaseModel):
    """A number worked out from answers rather than a group of respondents."""

    # sum: add the answers; midpoint: the middle of the chosen answer's range ("25-34" is 29.5).
    kind: Literal["sum", "midpoint"]
    sources: list[str] = Field(default_factory=list)
    # For a sum over one numeric list: only these rows (all rows when empty).
    rows: list[int | str] = Field(default_factory=list)


class BlockRotation(BaseModel):
    """Runs of consecutive questions shown in random order ("ROTATE SECTIONS A, B, C")."""

    # Each inner list is one section, in questionnaire order; sections are shuffled as wholes.
    groups: list[list[str]]
    note: str = ""


class DerivedVariable(BaseModel):
    """A hidden or classification variable the questionnaire defines, such as a reader segment.

    ``definition`` is the file's wording. ``values`` and ``after`` are the programmed
    form: the variable is computed after question ``after``.
    """

    id: str
    label: str = ""
    definition: str
    multiple: bool = False
    after: str | None = None
    values: list[DerivedValue] = Field(default_factory=list)
    # Set for a computed number (a total, an income midpoint); values stay empty then.
    compute: Computation | None = None
    unresolved: list[str] = Field(default_factory=list)


class QuestionnaireSource(BaseModel):
    """Where an imported questionnaire came from."""

    mode: Literal["exact", "reference"]
    filename: str
    checked_items: int = 0


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
    derived_variables: list[DerivedVariable] = Field(default_factory=list)
    source: QuestionnaireSource | None = None
    rotations: list[BlockRotation] = Field(default_factory=list)
    # Screen-out flags fire after this question unless a terminate is immediate.
    terminate_after: str | None = None
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
