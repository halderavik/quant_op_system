"""Canonical tab specification schema."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.expression import Expr


class BannerCategory(BaseModel):
    """One column segment inside a banner group."""

    label: str
    codes: list[Any]
    order: int = 0
    letter: str = ""
    n: int | None = None
    low_base: str = ""
    definition: str = ""


class Banner(BaseModel):
    """One group inside a banner plan. A plan is the letter A or B."""

    id: str
    label: str
    variable_name: str | None = None
    categories: list[BannerCategory] = Field(default_factory=list)
    include_total: bool = True
    plan: str = ""
    group: str = ""
    source_variable: str | None = None
    variable_note: str = ""


class SignificanceSpec(BaseModel):
    """Inferential settings. Weighted tests are refused without a design."""

    enabled: bool = False
    alpha: float = 0.05
    secondary_alpha: float = 0.10
    comparison: Literal["pairwise_columns"] = "pairwise_columns"
    correction: Literal["none", "holm"] = "none"
    minimum_effective_base: int = 30


class TableBase(BaseModel):
    """Who enters the denominator."""

    filter: Expr | None = None
    valid_response_rule: Literal["exclude_user_missing", "include_missing"] = "exclude_user_missing"


class TableSpec(BaseModel):
    """One crosstab definition. Overrides study defaults when set."""

    id: str
    title: str
    row_variable_names: list[str] = Field(default_factory=list)
    table_type: Literal["categorical", "multiple_response", "numeric", "grid"] = "categorical"
    banner_ids: list[str] = Field(default_factory=list)
    base: TableBase = Field(default_factory=TableBase)
    weight_variable: str | None = None
    statistics: list[str] = Field(
        default_factory=lambda: ["weighted_count", "unweighted_base", "weighted_base", "column_pct"]
    )
    display_decimals: int = 1
    significance: SignificanceSpec = Field(default_factory=SignificanceSpec)
    nets: list["NetSpec"] = Field(default_factory=list)
    top_box_codes: list[Any] = Field(default_factory=list)
    bottom_box_codes: list[Any] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    order: int = 0
    mention_denominator: bool = False
    section: str = ""
    plan_type: str = ""
    stub_label: str = ""
    base_text: str = "All"
    base_n: int | None = None
    row_instruction: str = ""
    banner_plans: list[str] = Field(default_factory=list)
    method: str = "crosstab"
    needs_confirmation: bool = False


class NetSpec(BaseModel):
    """A union of category codes or multi-response children."""

    id: str
    label: str
    child_codes: list[Any] = Field(default_factory=list)
    child_variables: list[str] = Field(default_factory=list)


class DerivedVariable(BaseModel):
    """A whitelist transformation. Recipes are not Python source."""

    name: str
    recipe: Literal["band", "recode", "reverse", "top_box", "net_flag"]
    source: str
    params: dict[str, Any] = Field(default_factory=dict)
    kind: str = ""
    definition: str = ""
    purpose: str = ""
    apply: bool = True


class StudyDefaults(BaseModel):
    """Defaults applied when a table omits a setting."""

    percent_type: Literal["column", "row", "total"] = "column"
    weight_variable: str | None = None
    alpha: float = 0.05
    minimum_unweighted_base_for_display: int = 30
    decimals: int = 1
    study_title: str = ""
    sample_note: str = ""
    sample_size: int | None = None
    assumptions: str = ""


class MappingItem(BaseModel):
    """Questionnaire question to dataset variable link."""

    question_id: str
    variable_names: list[str] = Field(default_factory=list)
    status: Literal["mapped", "unresolved", "excluded"] = "unresolved"
    reason: str | None = None


class TabSpec(BaseModel):
    """Whole-study or single-table specification."""

    spec_id: str
    questionnaire_revision: dict[str, Any] | None = None
    dataset_id: str | None = None
    study_defaults: StudyDefaults = Field(default_factory=StudyDefaults)
    banners: list[Banner] = Field(default_factory=list)
    tables: list[TableSpec]
    derived_variables: list[DerivedVariable] = Field(default_factory=list)
    unresolved_mappings: list[MappingItem] = Field(default_factory=list)
    exclusions: list[dict[str, str]] = Field(default_factory=list)
    schema_version: str = "tabspec/1"


class ExternalMappingPreview(BaseModel):
    """Detected mapping for a non-canonical workbook. Ambiguity blocks execution."""

    format_id: str
    mapping_confidence: Literal["high", "low"]
    mapped_fields: dict[str, str] = Field(default_factory=dict)
    unmapped_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    requires_confirmation: bool = False
    unsupported_entries: list[str] = Field(default_factory=list)
    tables: list[dict[str, Any]] = Field(default_factory=list)
