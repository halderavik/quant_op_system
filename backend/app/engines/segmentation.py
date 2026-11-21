"""Segmentation: compare K-means solutions, profile the segments, and build a typing tool.

For each number of segments the solution is scored on:

* **silhouette** (how well separated respondents are, -1 to 1),
* **Calinski-Harabasz** (between- to within-segment spread),
* **stability** (adjusted Rand agreement with a solution fitted on a different 80%
  of the sample and a different seed; 1 means the same segments come back),
* **smallest segment** share.

The recommended solution is the best-separated one whose smallest segment is at
least 5% of the sample and whose stability is at least 0.6.

The **typing tool** classifies new respondents from a few questions: a multinomial
logistic regression on raw answers, using the fewest variables whose holdout
accuracy is within five points of using them all.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.cluster import KMeans
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import adjusted_rand_score, calinski_harabasz_score, silhouette_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from app.errors import AppError

MIN_SHARE = 0.05
MIN_STABILITY = 0.6
_SILHOUETTE_SAMPLE = 3000
_TYPING_SIZES = (3, 5, 8, 12)
_TOP_FEATURES = 3


def compare_solutions(
    frame: pd.DataFrame,
    variables: list[str],
    k_values: list[int],
    labels: dict[str, str] | None = None,
    seed: int = 7,
) -> dict[str, Any]:
    """Fit one K-means solution per segment count and describe each.

    Args:
        frame: Respondent data.
        variables: Numeric segmentation variables (ratings, attitudes, behaviours).
        k_values: Segment counts to try, such as [3, 4, 5, 6].
        labels: Variable labels for naming and profiles.
        seed: Random seed.

    Returns:
        Base, dropped count, total means, one entry per solution, and the recommended k.

    Raises:
        AppError: Too few variables or respondents.
    """
    labels = labels or {}
    missing = [name for name in variables if name not in frame.columns]
    if missing:
        raise AppError(
            f"These variables are not in the data: {', '.join(missing)}.", "bad_request", 400
        )
    if len(variables) < 2:
        raise AppError("Choose at least two variables to segment on.", "bad_request", 400)
    data = frame[variables].apply(pd.to_numeric, errors="coerce")
    constant = [name for name in variables if data[name].nunique(dropna=True) < 2]
    if constant:
        raise AppError(
            f"These variables have only one value and cannot separate segments: {', '.join(constant)}.",
            "bad_request",
            400,
        )
    complete = data.dropna()
    dropped = int(len(data) - len(complete))
    ks = sorted({int(k) for k in k_values if 2 <= int(k) <= 12})
    if not ks:
        raise AppError("Try between 2 and 12 segments.", "bad_request", 400)
    if len(complete) < 20 * max(ks):
        raise AppError(
            f"{len(complete)} complete respondents is too few for {max(ks)} segments; "
            f"aim for at least {20 * max(ks)}.",
            "bad_request",
            400,
        )
    scaled = StandardScaler().fit_transform(complete)
    totals = {name: float(complete[name].mean()) for name in variables}
    spreads = {name: float(complete[name].std(ddof=0)) or 1.0 for name in variables}
    rng = np.random.default_rng(seed)
    sample = (
        rng.choice(len(scaled), _SILHOUETTE_SAMPLE, replace=False)
        if len(scaled) > _SILHOUETTE_SAMPLE
        else np.arange(len(scaled))
    )
    solutions = []
    for k in ks:
        model = KMeans(n_clusters=k, random_state=seed, n_init=20).fit(scaled)
        assigned = _by_size(model.labels_)
        solutions.append(
            {
                "k": k,
                "silhouette": round(float(silhouette_score(scaled[sample], assigned[sample])), 3),
                "calinski": round(float(calinski_harabasz_score(scaled, assigned)), 1),
                "stability": round(_stability(scaled, assigned, k, seed), 3),
                "profiles": _profiles(complete, assigned, variables, totals, spreads, labels),
                "typing": typing_tool(complete, assigned, variables, seed),
                "assignments": assigned.tolist(),
            }
        )
        sizes = [profile["share"] for profile in solutions[-1]["profiles"]]
        solutions[-1]["smallest"] = round(min(sizes), 3)
    return {
        "base": int(len(complete)),
        "dropped": dropped,
        "row_index": [
            int(i) if isinstance(i, (int, np.integer)) else str(i) for i in complete.index
        ],
        "totals": {name: round(value, 3) for name, value in totals.items()},
        "solutions": solutions,
        "recommended": recommend(solutions),
    }


def recommend(solutions: list[dict[str, Any]]) -> int:
    """The best-separated usable solution: big enough segments, stable enough."""
    usable = [
        s for s in solutions if s["smallest"] >= MIN_SHARE and s["stability"] >= MIN_STABILITY
    ]
    pool = usable or solutions
    return max(pool, key=lambda s: (s["silhouette"], -s["k"]))["k"]


def typing_tool(
    data: pd.DataFrame, assigned: np.ndarray, variables: list[str], seed: int = 7
) -> dict[str, Any]:
    """The shortest question set that classifies respondents almost as well as all of them.

    Args:
        data: Complete cases of the segmentation variables.
        assigned: Segment number (1 = largest) per row.
        variables: Candidate variables.
        seed: Random seed for the holdout split.

    Returns:
        Chosen variables, holdout accuracy (and with every variable), intercepts and
        coefficients per segment on the raw answer scale.
    """
    groups = pd.Series(assigned, index=data.index)
    strength = []
    for name in variables:
        samples = [data[name][groups == g].to_numpy() for g in sorted(groups.unique())]
        f_value = stats.f_oneway(*samples).statistic if len(samples) > 1 else 0.0
        strength.append((float(np.nan_to_num(f_value)), name))
    ranked = [name for _, name in sorted(strength, reverse=True)]
    stratify = assigned if min(np.bincount(assigned)[1:]) >= 2 else None
    train_x, test_x, train_y, test_y = train_test_split(
        data, assigned, test_size=0.25, random_state=seed, stratify=stratify
    )

    def fit(names: list[str]) -> tuple[float, LogisticRegression]:
        model = LogisticRegression(max_iter=2000)
        model.fit(train_x[names], train_y)
        return float(model.score(test_x[names], test_y)), model

    full_accuracy, _ = fit(ranked)
    chosen, accuracy, model = ranked, full_accuracy, None
    for size in _TYPING_SIZES:
        if size >= len(ranked):
            break
        score, candidate = fit(ranked[:size])
        if score >= full_accuracy - 0.05:
            chosen, accuracy, model = ranked[:size], score, candidate
            break
    if model is None:
        accuracy, model = fit(chosen)
    # Reason: refit on everyone for the published coefficients; accuracy stays the holdout score.
    final = LogisticRegression(max_iter=2000).fit(data[chosen], assigned)
    classes = [int(c) for c in final.classes_]
    coefficients = final.coef_
    intercepts = final.intercept_
    if len(classes) == 2:
        # Reason: a two-class model has one row; segment 1 scores 0, segment 2 the logit.
        coefficients = np.vstack([np.zeros_like(coefficients[0]), coefficients[0]])
        intercepts = np.array([0.0, intercepts[0]])
    return {
        "variables": chosen,
        "accuracy": round(accuracy, 3),
        "full_accuracy": round(full_accuracy, 3),
        "segments": classes,
        "intercepts": {
            str(c): round(float(b), 6) for c, b in zip(classes, intercepts, strict=True)
        },
        "coefficients": {
            str(c): {name: round(float(w), 6) for name, w in zip(chosen, row, strict=True)}
            for c, row in zip(classes, coefficients, strict=True)
        },
    }


def classify(typing: dict[str, Any], answers: dict[str, float]) -> int:
    """Score one respondent with a typing tool (the same arithmetic as the Excel file)."""
    scores = {
        segment: typing["intercepts"][segment]
        + sum(
            weight * float(answers[name])
            for name, weight in typing["coefficients"][segment].items()
        )
        for segment in typing["intercepts"]
    }
    return int(max(scores, key=lambda segment: scores[segment]))


def _by_size(raw: np.ndarray) -> np.ndarray:
    """Renumber segments 1..k from largest to smallest."""
    counts = np.bincount(raw)
    order = np.argsort(-counts, kind="stable")
    mapping = {int(old): new + 1 for new, old in enumerate(order)}
    return np.array([mapping[int(value)] for value in raw])


def _stability(scaled: np.ndarray, assigned: np.ndarray, k: int, seed: int) -> float:
    rng = np.random.default_rng(seed + 1)
    subset = rng.choice(len(scaled), int(0.8 * len(scaled)), replace=False)
    other = KMeans(n_clusters=k, random_state=seed + 1, n_init=10).fit(scaled[subset])
    return float(adjusted_rand_score(assigned, other.predict(scaled)))


def _profiles(
    data: pd.DataFrame,
    assigned: np.ndarray,
    variables: list[str],
    totals: dict[str, float],
    spreads: dict[str, float],
    labels: dict[str, str],
) -> list[dict[str, Any]]:
    profiles = []
    for segment in sorted(set(assigned.tolist())):
        rows = data[assigned == segment]
        means = {name: float(rows[name].mean()) for name in variables}
        gaps = sorted(
            (((means[name] - totals[name]) / spreads[name], name) for name in variables),
            key=lambda item: -abs(item[0]),
        )
        top = [
            {
                "variable": name,
                "label": labels.get(name, name),
                "z": round(z, 2),
                "direction": "higher" if z > 0 else "lower",
            }
            for z, name in gaps[:_TOP_FEATURES]
        ]
        profiles.append(
            {
                "segment": int(segment),
                "name": _name(top),
                "n": int(len(rows)),
                "share": round(len(rows) / len(data), 3),
                "means": {name: round(value, 3) for name, value in means.items()},
                "index": {
                    name: round(100 * means[name] / totals[name]) if totals[name] else None
                    for name in variables
                },
                "top": top,
            }
        )
    return profiles


def _name(top: list[dict[str, Any]]) -> str:
    """A working name from the two most distinctive variables; people rename it later."""
    parts = [
        f"{'High' if item['direction'] == 'higher' else 'Low'} {item['label']}"
        for item in top[:2]
        if abs(item["z"]) >= 0.3
    ]
    return " / ".join(parts) or "Close to average"


__all__ = ["classify", "compare_solutions", "recommend", "typing_tool"]
