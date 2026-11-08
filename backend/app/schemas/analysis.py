"""Analysis plan and result schemas."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.expression import Expr

MethodName = Literal[
    "descriptive",
    "correlation",
    "chi_square",
    "t_test",
    "anova",
    "linear_regression",
    "binary_logistic_regression",
    "ordinal_regression",
    "key_driver",
    "pca",
    "efa",
    "clustering",
    "discriminant",
    "correspondence",
    "reliability",
]


class VariableRole(BaseModel):
    """A user-supplied variable and how it is used. The app does not choose a dependent variable."""

    name: str
    role: str
    positive_code: Any = None


class AnalysisPlan(BaseModel):
    """Typed plan executed by a registered plugin."""

    analysis_id: str
    method: str
    dataset_id: str | None = None
    dependent: VariableRole | None = None
    predictors: list[str] = Field(default_factory=list)
    variables: list[str] = Field(default_factory=list)
    group: str | None = None
    var_a: str | None = None
    var_b: str | None = None
    weight_variable: str | None = None
    filter: Expr | None = None
    missing_strategy: Literal["listwise"] = "listwise"
    transformations: list[str] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)
    random_seed: int = 42
    deliverables: list[str] = Field(
        default_factory=lambda: ["report", "coefficient_table", "diagnostics", "code"]
    )


class AnalysisResult(BaseModel):
    """Machine-readable method output. Report claims point at these fields."""

    method: str
    sample_flow: dict[str, Any]
    descriptive: dict[str, Any] = Field(default_factory=dict)
    model_estimates: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    software_versions: dict[str, str] = Field(default_factory=dict)
    seed: int | None = None
    script: str = ""


class ReportClaim(BaseModel):
    """A numeric sentence bound to a result path."""

    path: str
    stated_value: float | int | str
    sentence: str


class AnalysisReport(BaseModel):
    """Narrative whose numbers are rendered from claims, not freehand."""

    title: str
    method: str
    sections: list[dict[str, str]]
    claims: list[ReportClaim]
    rendered: str
    caveats: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
