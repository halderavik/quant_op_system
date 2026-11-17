"""Report plan: what each slide of the final deck shows and how its numbers are computed."""

from typing import Literal

from pydantic import BaseModel, Field

SlideKind = Literal[
    "title",
    "text",
    "distribution",
    "grid_summary",
    "mean_summary",
    "nps",
    "rank_summary",
    "funnel",
    "profile",
    "analysis",
    "coding",
]
ChartKind = Literal["bar", "column", "stacked", "line", "table", "none"]
SlideStatus = Literal["planned", "needs_data", "low_base", "dropped", "done", "failed"]
Stage = Literal["draft", "questionnaire_final", "data_ready", "reported"]


class SlideSource(BaseModel):
    """How a slide's numbers are produced. Names refer to questionnaire ids and dataset columns."""

    question_ids: list[str] = Field(default_factory=list)
    variables: list[str] = Field(default_factory=list)
    # Reason: a dataset column to split by, such as S7 (gender); empty means Total only.
    banner: str = ""
    # Reason: "top2", "pct_yes", "mean" or "" (the default statistic for the kind).
    statistic: str = ""
    # Reason: a plain filter such as "Q5r1 == 1" (BrewCo owners); empty means all respondents.
    filter: str = ""
    # Reason: for analysis slides, the request the analysis agent receives.
    analysis_request: str = ""
    method: str = ""


class PlanSlide(BaseModel):
    """One slide of the planned deck."""

    id: str
    kind: SlideKind
    title: str
    purpose: str = ""
    objective_ids: list[str] = Field(default_factory=list)
    source: SlideSource = Field(default_factory=SlideSource)
    chart: ChartKind = "bar"
    notes: str = ""
    status: SlideStatus = "planned"
    status_reason: str = ""
    base_n: int | None = None
    origin: Literal["agent", "user"] = "agent"
    edited: bool = False


class PlanSection(BaseModel):
    """A chapter of the storyline."""

    id: str
    title: str
    purpose: str = ""
    slides: list[PlanSlide] = Field(default_factory=list)
    origin: Literal["agent", "user"] = "agent"
    edited: bool = False


class CoverageRow(BaseModel):
    """Where one questionnaire question is reported, or why it is not."""

    question_id: str
    text: str = ""
    slide_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class DataFacts(BaseModel):
    """What the planner learned from the data."""

    dataset_id: str = ""
    raw_n: int | None = None
    removed_by_cleaning: int | None = None
    final_n: int | None = None
    weight_variable: str = ""
    cleaning_summary: str = ""
    synthetic: bool = False
    missing_variables: list[str] = Field(default_factory=list)


class Objective(BaseModel):
    """A study objective the deck must answer."""

    id: str
    text: str
    question_ids: list[str] = Field(default_factory=list)


class ReportPlan(BaseModel):
    """The whole plan. Saved as the ``report_plan`` artifact and edited in the panel."""

    title: str
    stage: Stage = "draft"
    audience: str = ""
    objectives: list[Objective] = Field(default_factory=list)
    sections: list[PlanSection] = Field(default_factory=list)
    removed_slide_ids: list[str] = Field(default_factory=list)
    coverage: list[CoverageRow] = Field(default_factory=list)
    # auto: clean real data, skip synthetic data. skip / run: the user's choice.
    cleaning: Literal["auto", "skip", "run"] = "auto"
    data: DataFacts = Field(default_factory=DataFacts)
    questionnaire_ref: dict = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    def all_slides(self) -> list[PlanSlide]:
        """Every slide in storyline order."""
        return [slide for section in self.sections for slide in section.slides]
