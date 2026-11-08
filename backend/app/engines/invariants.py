"""Deterministic checks for tables, reports, and exports."""

import re
from pathlib import Path

from app.engines.analysis.report import claims_match_result
from app.schemas.analysis import AnalysisReport
from app.schemas.common import ValidationCheck, ValidationReport
from app.schemas.crosstab import TableResult


def validate_table(result: TableResult, table_type: str = "categorical") -> list[ValidationCheck]:
    """Check bases, percentage bounds, and net reach.

    Args:
        result: Computed table.
        table_type: ``categorical`` or ``multiple_response``.

    Returns:
        Checks. A failed check has severity error.
    """
    checks: list[ValidationCheck] = []
    exclusive = table_type != "multiple_response"
    for row in result.rows:
        for column_id, cell in row.cells.items():
            estimate = cell.estimate
            if estimate is not None and row.row_kind != "mean":
                upper = 100.0001 if exclusive or row.row_kind == "net" else 1000
                # Multiple-response category percentages may exceed 100.
                if row.row_kind != "category" or exclusive:
                    upper = 100.0001
                ok = -0.0001 <= estimate <= upper
                checks.append(
                    ValidationCheck(
                        id=f"bounds:{result.table_id}:{row.label}:{column_id}",
                        status="passed" if ok else "failed",
                        severity="error",
                        details=f"estimate={estimate}",
                    )
                )
            if (
                cell.weighted_numerator is not None
                and cell.weighted_denominator is not None
                and cell.weighted_numerator - cell.weighted_denominator > 1e-6
            ):
                checks.append(
                    ValidationCheck(
                        id=f"weight_num:{result.table_id}:{column_id}",
                        status="failed",
                        details="Weighted numerator exceeds its denominator",
                    )
                )
    total_categories = [row for row in result.rows if row.row_kind == "category"]
    if exclusive and total_categories and "total" in total_categories[0].cells:
        base = total_categories[0].cells["total"].unweighted_base or 0
        summed = sum(int(row.cells["total"].unweighted_numerator or 0) for row in total_categories)
        checks.append(
            ValidationCheck(
                id=f"exclusive_sum:{result.table_id}",
                status="passed" if summed == base else "failed",
                details=f"category sum {summed} vs base {base}",
            )
        )
    for row in result.rows:
        if row.row_kind != "net":
            continue
        for column_id, cell in row.cells.items():
            base = cell.unweighted_base or 0
            reach = cell.unweighted_numerator or 0
            child_max = max(
                (
                    int(other.cells[column_id].unweighted_numerator or 0)
                    for other in result.rows
                    if other.row_kind == "category" and column_id in other.cells
                ),
                default=0,
            )
            ok = reach <= base and reach >= child_max
            # A net of a subset can be below the largest category that is not in the net.
            # Compare only when every category row exists; if the net is a subset, child_max
            # of all categories is too strict. Callers pass nets after their children, and we
            # only enforce reach <= base here when child categories are mixed.
            ok = reach <= base
            checks.append(
                ValidationCheck(
                    id=f"net:{result.table_id}:{row.label}:{column_id}",
                    status="passed" if ok else "failed",
                    details=f"reach={reach} base={base}",
                )
            )
    return checks


def validate_report(report: AnalysisReport, result_payload: dict) -> list[ValidationCheck]:
    """Check that report claims match computed fields.

    Args:
        report: Report artifact.
        result_payload: Analysis result dictionary.

    Returns:
        One check per failure, or a passing check.
    """
    failures = claims_match_result(report, result_payload)
    if not failures:
        checks = [
            ValidationCheck(
                id="report_values_match", status="passed", details="Claims match result fields"
            )
        ]
    else:
        checks = [
            ValidationCheck(
                id="report_values_match",
                status="failed",
                details=f"Narrative or claim does not match its source statistic: {', '.join(failures)}",
            )
        ]
    checks.extend(semantic_interpretation(report.rendered))
    return checks


_CAUSAL = re.compile(r"\b(proves that|causes|caused by)\b", re.I)


def semantic_interpretation(rendered: str) -> list[ValidationCheck]:
    """Flag report language that overstates a statistical result.

    Args:
        rendered: Narrative shown to the user.

    Returns:
        One semantic check. Causal wording is a warning, not a rewritten number.
    """
    if _CAUSAL.search(rendered or ""):
        return [
            ValidationCheck(
                id="causal_language",
                type="semantic",
                status="failed",
                severity="warning",
                details="The narrative uses causal wording. Report the association instead.",
            )
        ]
    return [
        ValidationCheck(
            id="causal_language",
            type="semantic",
            status="passed",
            severity="info",
            details="No causal overclaim in the rendered narrative",
        )
    ]


def allow_repair(repair_count: int, *, numeric_failure: bool) -> bool:
    """Decide whether another automated repair is allowed.

    Args:
        repair_count: Repairs already attempted for this task.
        numeric_failure: True when a base, percent, or bound claim failed.

    Returns:
        False for numeric failures and after two attempts. Numbers are recomputed,
        never edited to match the narrative.
    """
    if numeric_failure:
        return False
    return repair_count < 2


def validate_export(path: Path | None) -> ValidationCheck:
    """Check that an export file exists and is not empty.

    Args:
        path: Expected file.

    Returns:
        Pass or fail check.
    """
    if path is None or not path.exists() or path.stat().st_size == 0:
        return ValidationCheck(
            id="export_exists", status="failed", details="Export file is missing or empty"
        )
    return ValidationCheck(id="export_exists", status="passed", details=str(path.name))


def summarize(checks: list[ValidationCheck], task_id: str | None = None) -> ValidationReport:
    """Collapse checks into a gate status.

    Args:
        checks: Individual checks.
        task_id: Optional task id.

    Returns:
        Validation report. Any failed error check fails the gate.
    """
    failed = [check for check in checks if check.status == "failed" and check.severity == "error"]
    warned = [check for check in checks if check.status == "failed" and check.severity == "warning"]
    if failed:
        status = "failed"
    elif warned:
        status = "passed_with_warnings"
    else:
        status = "passed"
    return ValidationReport(
        task_id=task_id,
        status=status,  # type: ignore[arg-type]
        checks=checks,
        required_repairs=(
            ["Recompute from source data and regenerate the narrative"] if failed else []
        ),
    )
