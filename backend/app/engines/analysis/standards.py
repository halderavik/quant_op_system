"""Quant market research standards the analysis engine applies to every plan and result.

These numbers are the house rules. The plan check, the runners, and the
quality review all read them from here, so a change in one place changes
what the planner is told, what the sandbox runs, and what gets flagged.
"""

# Reason: segmentation studies are read by marketers. Fewer than 4 segments is
# rarely actionable and more than 8 cannot be targeted, so every run tests 4-8.
SEGMENT_K_MIN = 4
SEGMENT_K_MAX = 8
# Reason: a segment under 5% of the base is too small to size or target.
MIN_SEGMENT_SHARE = 0.05
# Reason: silhouette below 0.25 means segments overlap heavily.
WEAK_SILHOUETTE = 0.25

# Reason: research tables suppress bases under 30 and mark bases under 50 as low.
MIN_BASE = 30
LOW_BASE = 50

# Reason: drivers and regressions need about 10 respondents per predictor.
CASES_PER_PREDICTOR = 10
MAX_VIF = 5.0
LOW_R_SQUARED = 0.10

# Reason: factor analysis is unreliable below KMO 0.6 or when items do not correlate.
MIN_KMO = 0.6
MIN_LOADING = 0.4

# Reason: chi-square is unreliable when over 20% of expected cells are under 5.
MAX_SPARSE_SHARE = 0.20

CONFIDENCE = 0.95
ALPHA = 1 - CONFIDENCE


def rule_lines() -> list[str]:
    """Return the standards as short sentences for the plan, the planner, and the workbook.

    Returns:
        One sentence per rule.
    """
    return [
        f"Segmentation tests {SEGMENT_K_MIN} to {SEGMENT_K_MAX} segments and keeps the best "
        f"silhouette among solutions whose smallest segment is at least "
        f"{MIN_SEGMENT_SHARE:.0%} of the base. Segments are profiled on variables that were "
        "not clustering features.",
        "Driver analysis reports an importance ranking from Johnson's relative weights, "
        "which share R-squared among correlated drivers, with standardized coefficients.",
        f"Bases under {MIN_BASE} are flagged as too small to report; bases under {LOW_BASE} "
        "are flagged as directional.",
        f"Models need {CASES_PER_PREDICTOR} respondents per predictor; VIF above {MAX_VIF:g} "
        "is flagged as collinear.",
        f"Factor and component analysis report KMO (flagged below {MIN_KMO:g}), Bartlett's "
        f"test, variance explained, and items that load below {MIN_LOADING:g}.",
        f"Significance is read at {CONFIDENCE:.0%} confidence. ANOVA adds Tukey pairwise "
        "comparisons; chi-square adds Cramer's V and checks sparse cells.",
        "Don't know, Not sure, Prefer not to say, and Refused codes are excluded from scales.",
    ]
