"""Numeric crosstab result contract."""

from typing import Literal

from pydantic import BaseModel, Field


class CellResult(BaseModel):
    """One table cell. ``display_value`` is rounded text; ``estimate`` is numeric."""

    estimate: float | None = None
    display_value: str | None = None
    weighted_numerator: float | None = None
    weighted_denominator: float | None = None
    unweighted_numerator: int | None = None
    unweighted_base: int | None = None
    weighted_base: float | None = None
    effective_base_if_available: float | None = None
    p_value_if_tested: float | None = None
    significance_letters: str = ""
    test_status: Literal["tested", "not_tested"] = "not_tested"
    test_method: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ColumnHeader(BaseModel):
    """A banner column, including the total column."""

    id: str
    label: str
    letter: str = ""


class ResultRow(BaseModel):
    """A stub row of cells keyed by column id."""

    code: str | int | float | None = None
    label: str
    row_kind: Literal["category", "net", "mean", "top_box", "bottom_box", "stat"] = "category"
    cells: dict[str, CellResult]


class TableResult(BaseModel):
    """Computed table. Counts are not formatted strings."""

    table_id: str
    title: str
    dataset_id: str | None = None
    tab_spec_version: int | None = None
    columns: list[ColumnHeader]
    rows: list[ResultRow]
    footnotes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    validation: dict[str, object] = Field(default_factory=dict)
    weight_variable: str | None = None
    percent_type: str = "column"


class TabBook(BaseModel):
    """A batch of tables plus an exception log. Nothing is skipped silently."""

    tables: list[TableResult] = Field(default_factory=list)
    exceptions: list[dict[str, str]] = Field(default_factory=list)
