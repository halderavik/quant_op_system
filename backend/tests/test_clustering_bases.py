"""K-means keeps a shared base when named variables are asked of different people."""

import numpy as np
import pandas as pd
import pytest

from app.engines.analysis.registry import run_plan
from app.engines.analysis.report import analysis_summary
from app.errors import AppError
from app.schemas.analysis import AnalysisPlan
from app.schemas.expression import Comparison


def _plan(variables: list[str], **kwargs: object) -> AnalysisPlan:
    """Build a clustering plan.

    Args:
        variables: Feature names.
        **kwargs: Extra plan fields.

    Returns:
        Clustering plan.
    """
    return AnalysisPlan(
        analysis_id="seg",
        method="clustering",
        variables=variables,
        random_seed=7,
        options={"k": 2},
        **kwargs,
    )


def test_complete_rows_stay_in_the_segmentation() -> None:
    """A request whose variables are filled for everyone uses every row."""
    frame = pd.DataFrame({"x": [1.0, 2.0, 3.0, 8.0], "y": [1.0, 1.5, 7.0, 8.0]})
    result = run_plan(frame, _plan(["x", "y"]))
    assert result.sample_flow["valid_n"] == 4
    assert result.sample_flow["variables_used"] == ["x", "y"]
    assert result.sample_flow["variables_excluded"] == []
    assert sum(result.model_estimates["sizes"].values()) == 4
    assert not any(item.startswith("Left out ") for item in result.warnings)


def test_empty_and_smaller_bases_are_left_out() -> None:
    """Empty items and a small skip group do not wipe the segmentation."""
    rng = np.random.default_rng(0)
    wide = rng.normal(size=100)
    wide[80:] = np.nan
    narrow = rng.normal(size=100)
    narrow[:70] = np.nan
    frame = pd.DataFrame(
        {
            "attitude": rng.normal(size=100),
            "importance": rng.normal(size=100),
            "wide": wide,
            "narrow": narrow,
            "unused": np.nan,
        }
    )
    result = run_plan(frame, _plan(["attitude", "importance", "wide", "narrow", "unused"]))
    assert result.sample_flow["valid_n"] == 80
    assert result.sample_flow["variables_used"] == ["attitude", "importance", "wide"]
    excluded = {item["name"] for item in result.sample_flow["variables_excluded"]}
    assert excluded == {"narrow", "unused"}
    summary = analysis_summary("clustering", result)
    assert "Ran k-means clustering on 80 complete rows." in summary
    assert "unused" in summary
    assert "narrow" in summary
    assert sum(result.model_estimates["sizes"].values()) == 80


def test_clustering_refuses_a_base_smaller_than_three_rows() -> None:
    """Two answers, a missing name, and a filter that leaves two rows do not run."""
    sparse = pd.DataFrame(
        {
            "left": [1.0, 2.0, np.nan, np.nan, np.nan, np.nan],
            "right": [np.nan, np.nan, 1.0, 2.0, np.nan, np.nan],
        }
    )
    with pytest.raises(AppError) as caught:
        run_plan(sparse, _plan(["left", "right"]))
    assert caught.value.code == "small_sample"
    assert "Fewer than 3 complete rows" in caught.value.message

    with pytest.raises(AppError) as missing:
        run_plan(sparse, _plan(["left", "absent"]))
    assert missing.value.code == "missing_variable"

    filtered = pd.DataFrame(
        {
            "keep": [1, 1, 0, 0, 0],
            "x": [1.0, 2.0, 3.0, 4.0, 5.0],
            "y": [2.0, 3.0, 4.0, 5.0, 6.0],
        }
    )
    plan = _plan(
        ["x", "y"],
        filter=Comparison(op="eq", ref="keep", value=1),
    )
    with pytest.raises(AppError) as too_few:
        run_plan(filtered, plan)
    assert too_few.value.code == "small_sample"
