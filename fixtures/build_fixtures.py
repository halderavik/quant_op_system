"""Write the synthetic fixtures. Expected numbers are also in expected_results.json."""

from pathlib import Path

import numpy as np
import pandas as pd
import pyreadstat

ROOT = Path(__file__).resolve().parent


def survey_small() -> None:
    """Write the six-respondent trust file used by the golden crosstab."""
    frame = pd.DataFrame(
        {
            "respondent_id": [1, 2, 3, 4, 5, 6],
            "gender": [1, 1, 1, 2, 2, 2],
            "trust": [1, 1, 2, 2, 99, 1],
            "weight": [1.0, 1.0, 0.0, 2.0, 1.0, 1.0],
            "brand_a": [1, 1, 0, 0, 1, 0],
            "brand_b": [1, 0, 1, 0, 0, 0],
            "comment": ["Great quality", "Too expensive", "", "Reliable", "n/a", "Fast delivery"],
        }
    )
    pyreadstat.write_sav(
        frame,
        ROOT / "survey_small.sav",
        column_labels=["Respondent", "Gender", "Trust", "Weight", "Brand A", "Brand B", "Comment"],
        variable_value_labels={
            "gender": {1: "Male", 2: "Female"},
            "trust": {1: "Low", 2: "High"},
        },
        missing_ranges={"trust": [{"lo": 98, "hi": 99}]},
    )


def survey_analysis() -> None:
    """Write a small labelled file for regression and clustering checks."""
    rng = np.random.default_rng(7)
    trust = rng.normal(size=40)
    age = rng.normal(size=40)
    probability = 1 / (1 + np.exp(-(-0.2 + 0.8 * trust)))
    frame = pd.DataFrame(
        {
            "respondent_id": np.arange(1, 41),
            "purchase": rng.binomial(1, probability),
            "trust": trust,
            "age": age,
            "segment_score": rng.normal(size=40),
        }
    )
    pyreadstat.write_sav(frame, ROOT / "survey_analysis.sav")


def open_end_truth() -> None:
    """Write 30 labelled comments. Codes are the oracle, not model output."""
    comments = [
        ("Great quality", "C01"),
        ("Too expensive", "C02"),
        ("Fast shipping", "C03"),
        ("Poor support", "C04"),
        ("Love the taste", "C01"),
        ("Price is high", "C02"),
        ("Arrived quickly", "C03"),
        ("Rude staff", "C04"),
        ("Excellent product", "C01"),
        ("Costs too much", "C02"),
    ]
    rows = []
    for index in range(30):
        text, code = comments[index % len(comments)]
        rows.append({"respondent_id": index + 1, "comment": text, "true_code": code})
    pd.DataFrame(rows).to_csv(ROOT / "oe_labeled.csv", index=False)


if __name__ == "__main__":
    survey_small()
    survey_analysis()
    open_end_truth()
