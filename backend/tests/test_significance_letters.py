"""Significance letters on mean rows, certain differences, and the workbook cover note."""

from io import BytesIO

import pandas as pd
import pytest
from openpyxl import load_workbook
from scipy import stats

from app.engines.crosstab import run_table
from app.engines.significance import ColumnCounts, _two_means, apply_pairwise_letters
from app.engines.tabbook_excel import export_tabbook
from app.schemas.crosstab import CellResult, TabBook
from app.schemas.tabspec import (
    Banner,
    BannerCategory,
    SignificanceSpec,
    StudyDefaults,
    TableSpec,
)

_SIG = SignificanceSpec(enabled=True, alpha=0.05, secondary_alpha=0.10, minimum_effective_base=20)


def _meta() -> list[dict]:
    return [
        {"name": "age", "label": "Age", "value_labels": {}, "user_missing_values": []},
        {"name": "used", "label": "Used", "value_labels": {"1": "Yes", "2": "No"}},
        {"name": "group", "label": "Group", "value_labels": {"1": "A", "2": "B"}},
    ]


def _banners() -> list[Banner]:
    return [
        Banner(
            id="bn1",
            label="Group",
            variable_name="group",
            categories=[
                BannerCategory(label="Young", codes=[1]),
                BannerCategory(label="Old", codes=[2]),
            ],
        )
    ]


def _frame() -> pd.DataFrame:
    """Forty respondents per group; the old group is about ten years older."""
    young = [25 + (index % 10) for index in range(40)]
    old = [35 + (index % 12) for index in range(40)]
    return pd.DataFrame(
        {
            "group": [1] * 40 + [2] * 40,
            "age": young + old,
            "used": [1] * 40 + [2] * 40,
        }
    )


def _run(row: str, table_type: str = "categorical"):
    spec = TableSpec(
        id="T1",
        title=f"{row} by group",
        row_variable_names=[row],
        banner_ids=["bn1"],
        table_type=table_type,
        significance=_SIG,
    )
    return run_table(_frame(), _meta(), spec, StudyDefaults(), _banners())


def test_mean_rows_get_welch_letters() -> None:
    """The older column's mean is marked higher than the younger column's."""
    result = _run("age", "numeric")
    row = result.rows[0]
    assert row.row_kind == "mean"
    old, young = row.cells["bn1:Old"], row.cells["bn1:Young"]
    assert old.significance_letters == "A"
    assert young.significance_letters == ""
    assert old.test_method == "welch_two_mean_t"
    frame = _frame()
    reference = stats.ttest_ind(
        frame.loc[frame.group == 2, "age"], frame.loc[frame.group == 1, "age"], equal_var=False
    )
    assert old.p_value_if_tested == pytest.approx(reference.pvalue)
    assert any("Welch t-test for means" in note for note in result.footnotes)


def test_welch_matches_scipy_with_unequal_spread() -> None:
    """Hand-built summary statistics agree with scipy's Welch test."""
    left = ColumnCounts("a", "A", 0, 50, 7.2, 1.1)
    right = ColumnCounts("b", "B", 0, 35, 6.6, 2.4)
    expected = stats.ttest_ind_from_stats(7.2, 1.1, 50, 6.6, 2.4, 35, equal_var=False).pvalue
    assert _two_means(left, right) == pytest.approx(expected)


def test_all_against_none_is_significant() -> None:
    """100% against 0% has no sampling variance; the difference is still certain."""
    result = _run("used")
    yes = next(row for row in result.rows if row.label == "Yes")
    assert yes.cells["bn1:Young"].significance_letters == "B"
    assert yes.cells["bn1:Old"].significance_letters == ""


def test_small_mean_column_is_marked_and_skipped() -> None:
    """A mean column below the minimum base gets '.' like a percentage column."""
    cells = {key: CellResult(estimate=value) for key, value in (("a", 5.0), ("b", 4.0), ("c", 3.0))}
    apply_pairwise_letters(
        cells,
        [
            ColumnCounts("a", "A", 0, 100, 5.0, 1.0),
            ColumnCounts("b", "B", 0, 100, 4.0, 1.0),
            ColumnCounts("c", "C", 0, 10, 3.0, 1.0),
        ],
        alpha=0.05,
        correction="none",
        minimum_base=20,
        weighted=False,
        method="mean",
    )
    assert cells["a"].significance_letters == "B"
    assert cells["c"].significance_letters == "."


def test_cover_note_states_the_settings_used() -> None:
    """The contents sheet reports the real minimum base and confidence levels."""
    result = _run("age", "numeric")
    sheet = load_workbook(BytesIO(export_tabbook(TabBook(tables=[result]))))["Table of Contents"]
    assert "Welch t-test for means" in sheet["A3"].value
    assert "below 20" in sheet["A4"].value
    assert "30 or less" not in sheet["A4"].value
    assert "95%" in sheet["A5"].value and "90%" in sheet["A5"].value


def test_cover_note_without_testing_says_so() -> None:
    """A book with no tested tables does not claim a method was applied."""
    spec = TableSpec(id="T1", title="t", row_variable_names=["used"], banner_ids=["bn1"])
    result = run_table(_frame(), _meta(), spec, StudyDefaults(), _banners())
    sheet = load_workbook(BytesIO(export_tabbook(TabBook(tables=[result]))))["Table of Contents"]
    assert "not requested" in sheet["A3"].value


def test_weighted_test_uses_the_effective_base() -> None:
    """Weighted 60% vs 40% on effective bases 50 and 80, checked by hand."""
    from math import sqrt
    from statistics import NormalDist

    cells = {"a": CellResult(estimate=60.0), "b": CellResult(estimate=40.0)}
    apply_pairwise_letters(
        cells,
        [
            ColumnCounts("a", "A", 70, 100, 60.0, effective_base=50.0),
            ColumnCounts("b", "B", 30, 100, 40.0, effective_base=80.0),
        ],
        alpha=0.05,
        correction="none",
        minimum_base=20,
        weighted=True,
    )
    z = 0.2 / sqrt(0.6 * 0.4 / 50 + 0.4 * 0.6 / 80)
    expected = 2 * (1 - NormalDist().cdf(z))
    assert cells["a"].p_value_if_tested == pytest.approx(expected)
    assert cells["a"].significance_letters == "B"
    assert cells["a"].test_method == "unpooled_two_proportion_z_effective_base"
