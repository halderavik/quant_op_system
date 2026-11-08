"""Render analysis narrative from result paths so numbers are not typed by hand."""

import re
from typing import Any

from app.schemas.analysis import AnalysisReport, AnalysisResult, ReportClaim


def lookup(payload: dict[str, Any], path: str) -> Any:
    """Resolve a dotted path against a result dictionary.

    Args:
        payload: Result dictionary.
        path: Dotted path such as ``metrics.r_squared``.

    Returns:
        Value at that path.
    """
    current: Any = payload
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise KeyError(path)
    return current


def build_report(title: str, result: AnalysisResult) -> AnalysisReport:
    """Build claims and a rendered narrative from a computed result.

    Args:
        title: Report title.
        result: Computed analysis result.

    Returns:
        Report whose rendered text is a join of claim sentences.
    """
    claims: list[ReportClaim] = []
    for name, estimate in result.model_estimates.items():
        if not isinstance(estimate, dict):
            continue
        for key, value in estimate.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            path = f"model_estimates.{name}.{key}"
            claims.append(
                ReportClaim(
                    path=path,
                    stated_value=value,
                    sentence=f"{name} {key.replace('_', ' ')} is {value}.",
                )
            )
    for name, value in result.metrics.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        claims.append(
            ReportClaim(
                path=f"metrics.{name}",
                stated_value=value,
                sentence=f"{name.replace('_', ' ')} is {value}.",
            )
        )
    claims.append(
        ReportClaim(
            path="sample_flow.valid_n",
            stated_value=result.sample_flow.get("valid_n", 0),
            sentence=f"The analysis sample is {result.sample_flow.get('valid_n')} complete respondents.",
        )
    )
    rendered = render_claims(claims)
    caveats = list(result.warnings) + [
        "Associations are sample estimates. They are not causal effects.",
        "Fit statistics describe this sample. They are not a holdout validation unless a split is reported.",
    ]
    return AnalysisReport(
        title=title,
        method=result.method,
        sections=[
            {"id": "findings", "narrative": rendered, "editable": "true"},
            {"id": "caveats", "narrative": " ".join(caveats), "editable": "true"},
        ],
        claims=claims,
        rendered=rendered,
        caveats=caveats,
        provenance={"method": result.method, "seed": result.seed},
    )


def render_claims(claims: list[ReportClaim]) -> str:
    """Join claim sentences in order.

    Args:
        claims: Bound claims.

    Returns:
        Rendered findings text.
    """
    return "\n".join(claim.sentence for claim in claims)


def unclaimed_numbers(text: str, claims: list[ReportClaim]) -> list[str]:
    """Return numbers in prose that are not a claim's stated value.

    Args:
        text: Edited narrative or caveat.
        claims: Computed claims. These are the only numbers the prose may state.

    Returns:
        Number tokens that do not match a stated value.
    """
    allowed = [
        float(claim.stated_value)
        for claim in claims
        if isinstance(claim.stated_value, (int, float)) and not isinstance(claim.stated_value, bool)
    ]
    unknown: list[str] = []
    for token in re.findall(r"\d+(?:\.\d+)?", text or ""):
        value = float(token)
        if not any(abs(value - item) <= 1e-6 for item in allowed):
            unknown.append(token)
    return unknown


def claims_match_result(report: AnalysisReport, result_payload: dict[str, Any]) -> list[str]:
    """Return paths whose stated value does not match the computed result.

    Args:
        report: Report under review.
        result_payload: Analysis result as a dictionary.

    Returns:
        Failing paths.
    """
    failures: list[str] = []
    for claim in report.claims:
        try:
            actual = lookup(result_payload, claim.path)
        except KeyError:
            failures.append(claim.path)
            continue
        if isinstance(actual, float) or isinstance(claim.stated_value, float):
            if abs(float(actual) - float(claim.stated_value)) > 1e-6:
                failures.append(claim.path)
        elif actual != claim.stated_value:
            failures.append(claim.path)
    expected = render_claims(report.claims)
    if report.rendered != expected:
        failures.append("rendered")
    return failures
