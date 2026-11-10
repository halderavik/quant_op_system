"""Hand-checked crosstab cases. Expected numbers are literals, not engine output."""

import pandas as pd
import pytest

from app.engines.crosstab import run_table
from app.errors import AppError
from app.schemas.tabspec import (
    Banner,
    BannerCategory,
    NetSpec,
    SignificanceSpec,
    StudyDefaults,
    TableBase,
    TableSpec,
)


def _meta() -> list[dict]:
    """Return a small variable dictionary.

    Returns:
        Variable metadata.
    """
    return [
        {
            "name": "trust",
            "label": "Trust",
            "value_labels": {"1": "Low", "2": "High"},
            "user_missing_values": [99],
        },
        {
            "name": "gender",
            "label": "Gender",
            "value_labels": {"1": "Male", "2": "Female"},
            "user_missing_values": [],
        },
        {"name": "weight", "label": "Weight", "value_labels": {}, "user_missing_values": []},
        {"name": "brand_a", "label": "Brand A", "value_labels": {}, "user_missing_values": []},
        {"name": "brand_b", "label": "Brand B", "value_labels": {}, "user_missing_values": []},
    ]


def _frame() -> pd.DataFrame:
    """Six respondents with a zero weight and a user-missing code.

    Returns:
        Data frame.
    """
    return pd.DataFrame(
        {
            "gender": [1, 1, 1, 2, 2, 2],
            "trust": [1, 1, 2, 2, 99, 1],
            "weight": [1, 1, 0, 2, 1, 1],
        }
    )


def _table(**kwargs: object) -> TableSpec:
    """Build the trust-by-gender table.

    Args:
        **kwargs: TableSpec overrides.

    Returns:
        Table spec.
    """
    payload = dict(
        id="T001",
        title="Trust by gender",
        row_variable_names=["trust"],
        banner_ids=["bn1"],
        weight_variable="weight",
    )
    payload.update(kwargs)
    return TableSpec(**payload)


def _banners() -> list[Banner]:
    """Gender banner.

    Returns:
        Banners.
    """
    return [
        Banner(
            id="bn1",
            label="Gender",
            variable_name="gender",
            categories=[
                BannerCategory(label="Male", codes=[1]),
                BannerCategory(label="Female", codes=[2]),
            ],
        )
    ]


def test_weighted_column_percents_match_hand_calculation() -> None:
    """Zero weights stay in the unweighted base and out of the weighted base."""
    result = run_table(
        _frame(), _meta(), _table(), StudyDefaults(weight_variable="weight"), _banners()
    )
    total = {row.label: row.cells["total"] for row in result.rows}
    assert total["Low"].unweighted_base == 5
    assert total["Low"].weighted_base == pytest.approx(5)
    assert total["Low"].unweighted_numerator == 3
    assert total["Low"].weighted_numerator == pytest.approx(3)
    assert total["Low"].estimate == pytest.approx(60)
    assert total["High"].estimate == pytest.approx(40)
    male = next(row for row in result.rows if row.label == "High").cells["bn1:Male"]
    assert male.unweighted_base == 3
    assert male.weighted_base == pytest.approx(2)
    assert male.unweighted_numerator == 1
    assert male.weighted_numerator == pytest.approx(0)
    assert male.estimate == pytest.approx(0)


def test_negative_weight_is_rejected() -> None:
    """Negative weights are an error, not a quiet recode."""
    frame = _frame()
    frame.loc[0, "weight"] = -1
    with pytest.raises(AppError) as caught:
        run_table(frame, _meta(), _table(), StudyDefaults(), _banners())
    assert caught.value.code == "negative_weight"


def test_multi_response_net_dedupes_respondents() -> None:
    """A respondent in both brands counts once in the net."""
    frame = pd.DataFrame(
        {
            "brand_a": [1, 1, 0, 0],
            "brand_b": [1, 0, 1, 0],
            "weight": [1, 1, 2, 1],
        }
    )
    table = TableSpec(
        id="T002",
        title="Brands",
        row_variable_names=["brand_a", "brand_b"],
        table_type="multiple_response",
        weight_variable="weight",
        nets=[NetSpec(id="N1", label="Any brand", child_variables=["brand_a", "brand_b"])],
    )
    result = run_table(frame, _meta(), table, StudyDefaults(), [])
    by_label = {row.label: row.cells["total"] for row in result.rows}
    assert by_label["Brand A"].unweighted_numerator == 2
    assert by_label["Brand A"].estimate == pytest.approx(40)
    assert by_label["Any brand"].unweighted_numerator == 3
    assert by_label["Any brand"].unweighted_numerator <= by_label["Any brand"].unweighted_base


def test_significance_runs_unweighted_and_refuses_weights() -> None:
    """A large unweighted contrast is tested. Varying weights are not given a p-value."""
    frame = pd.DataFrame(
        {
            "trust": [1] * 18 + [2] * 2 + [1] * 2 + [2] * 18,
            "gender": [1] * 20 + [2] * 20,
        }
    )
    spec = _table(
        weight_variable=None, significance=SignificanceSpec(enabled=True, minimum_effective_base=10)
    )
    result = run_table(frame, _meta(), spec, StudyDefaults(), _banners())
    low = next(row for row in result.rows if row.label == "Low")
    assert low.cells["bn1:Male"].test_status == "tested"
    assert low.cells["bn1:Male"].test_method == "unpooled_two_proportion_z"
    assert low.cells["bn1:Male"].significance_letters == "B"
    assert low.cells["bn1:Male"].p_value_if_tested is not None
    weighted = run_table(
        _frame(),
        _meta(),
        _table(significance=SignificanceSpec(enabled=True, minimum_effective_base=1)),
        StudyDefaults(),
        _banners(),
    )
    assert any(
        cell.test_status == "not_tested" for row in weighted.rows for cell in row.cells.values()
    )
    assert all(
        cell.p_value_if_tested is None for row in weighted.rows for cell in row.cells.values()
    )


def test_letters_use_lowercase_and_skip_a_small_base() -> None:
    """A modest contrast is lowercase, and a base of 30 or below is marked with a dot."""
    from app.engines.significance import ColumnCounts, apply_pairwise_letters
    from app.schemas.crosstab import CellResult

    cells = {
        "small": CellResult(estimate=50),
        "high": CellResult(estimate=55),
        "low": CellResult(estimate=45),
    }
    columns = [
        ColumnCounts("small", "A", 10, 20, 50),
        ColumnCounts("high", "B", 99, 180, 55),
        ColumnCounts("low", "C", 81, 180, 45),
    ]
    apply_pairwise_letters(
        cells,
        columns,
        alpha=0.05,
        secondary_alpha=0.10,
        correction="none",
        minimum_base=30,
        weighted=False,
    )
    assert cells["small"].significance_letters == "."
    assert cells["small"].test_status == "not_tested"
    assert cells["high"].significance_letters == "c"
    assert cells["high"].test_status == "tested"


def test_tabbook_uses_the_stacked_layout() -> None:
    """The workbook has a contents sheet, a stacked sheet, and percent number formats."""
    from io import BytesIO

    from openpyxl import load_workbook

    from app.engines.tabbook_excel import export_tabbook
    from app.schemas.crosstab import TabBook

    frame = pd.DataFrame({"trust": [1] * 30 + [2] * 10, "gender": [1] * 20 + [2] * 20})
    spec = _table(
        weight_variable=None,
        significance=SignificanceSpec(enabled=True, minimum_effective_base=10),
    )
    result = run_table(frame, _meta(), spec, StudyDefaults(), _banners())
    workbook = load_workbook(BytesIO(export_tabbook(TabBook(tables=[result]))))
    assert workbook.sheetnames == ["Table of Contents", "Crosstabs_1"]
    assert "UNPOOLED" in workbook["Table of Contents"]["A3"].value
    assert workbook["Table of Contents"]["D8"].value == "Jump to Table"
    link = workbook["Table of Contents"]["D8"].hyperlink
    target = f"{link.target or ''}{link.location or ''}"
    assert "Crosstabs_1" in target and "A1" in target
    crosses = workbook["Crosstabs_1"]
    assert crosses["A1"].value == "  Trust by gender"
    assert str(crosses["A1"].font.color.rgb).endswith("FFFFFF")
    assert crosses["A2"].value.startswith("N=")
    assert "Gender: gender" in crosses["A2"].value
    assert crosses["B3"].value == "gender"
    percent = crosses["B5"]
    assert percent.number_format == "0.0%"
    assert percent.value == pytest.approx(result.rows[0].cells["bn1:Male"].estimate / 100)


def test_unknown_variable_fails() -> None:
    """A missing stub variable is an error."""
    with pytest.raises(AppError):
        run_table(
            _frame(), _meta(), _table(row_variable_names=["not_a_var"]), StudyDefaults(), _banners()
        )


def test_filter_expression_rejects_code_like_refs() -> None:
    """Derived and filter references cannot be Python expressions."""
    from app.schemas.expression import Comparison

    table = _table(
        base=TableBase(filter=Comparison(op="eq", ref="gender", value=1)), weight_variable=None
    )
    result = run_table(_frame(), _meta(), table, StudyDefaults(), _banners())
    assert result.rows[0].cells["total"].unweighted_base == 3
    with pytest.raises(Exception):
        Comparison(op="eq", ref="__import__", value=1)
