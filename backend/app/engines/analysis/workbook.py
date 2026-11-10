"""Excel workbook for one analysis run."""

from io import BytesIO
from typing import Any

from openpyxl import Workbook

from app.schemas.analysis import AnalysisReport, AnalysisWorkflow


def workbook_bytes(
    workflow: AnalysisWorkflow, result: dict[str, Any], report: AnalysisReport
) -> bytes:
    """Build the detailed workbook for a finished analysis.

    Args:
        workflow: Plan that ran.
        result: Computed payload from the sandbox.
        report: Narrative bound to that payload.

    Returns:
        XLSX bytes.
    """
    book = Workbook()
    _plan_sheet(book, workflow)
    _sample_sheet(book, result)
    _rows_sheet(book, "Imputation", _impute_rows(result))
    _rows_sheet(book, "Recodes", _recode_rows(result))
    _method_sheet(book, result)
    _profile_sheet(book, result)
    _rows_sheet(book, "Diagnostics", _diagnostic_rows(result))
    summary = book.create_sheet("Summary")
    summary.append(["Summary"])
    for line in (report.rendered or "").splitlines():
        summary.append([line])
    if report.caveats:
        summary.append([])
        summary.append(["Caveats"])
        for caveat in report.caveats:
            summary.append([caveat])
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _plan_sheet(book: Workbook, workflow: AnalysisWorkflow) -> None:
    """Write the plan onto the first sheet.

    Args:
        book: Workbook.
        workflow: Plan.
    """
    sheet = book.active
    sheet.title = "Plan"
    sheet.append(["Objective", workflow.objective])
    sheet.append(["Seed", workflow.random_seed])
    sheet.append([])
    sheet.append(["Step", "Kind", "Reason", "Variables", "Settings"])
    for index, step in enumerate(workflow.steps, start=1):
        settings = []
        if step.method:
            settings.append(step.method)
        if step.strategy:
            settings.append(step.strategy)
        if step.k:
            settings.append(f"k={step.k}")
        if step.kind in {"top_box", "bottom_box"}:
            settings.append(f"box={step.box or 2}")
        sheet.append(
            [
                index,
                step.kind,
                step.reason,
                ", ".join(step.variables),
                ", ".join(settings),
            ]
        )


def _sample_sheet(book: Workbook, result: dict[str, Any]) -> None:
    """Write the sample flow.

    Args:
        book: Workbook.
        result: Computed payload.
    """
    sheet = book.create_sheet("Sample")
    sheet.append(["Field", "Value"])
    flow = result.get("sample_flow") or {}
    for key, value in flow.items():
        if isinstance(value, (dict, list)):
            continue
        sheet.append([key, value])


def _method_sheet(book: Workbook, result: dict[str, Any]) -> None:
    """Write estimates and metrics.

    Args:
        book: Workbook.
        result: Computed payload.
    """
    sheet = book.create_sheet("Method")
    sheet.append(["Section", "Name", "Field", "Value"])
    for name, estimate in (result.get("model_estimates") or {}).items():
        if isinstance(estimate, dict):
            for field, value in estimate.items():
                if not isinstance(value, (dict, list)):
                    sheet.append(["estimate", name, field, value])
        else:
            sheet.append(["estimate", name, "", estimate])
    for name, value in (result.get("metrics") or {}).items():
        if not isinstance(value, (dict, list)):
            sheet.append(["metric", name, "", value])


def _profile_sheet(book: Workbook, result: dict[str, Any]) -> None:
    """Write segment profile tables under one another.

    Args:
        book: Workbook.
        result: Computed payload.
    """
    sheet = book.create_sheet("Profile")
    tables = ((result.get("diagnostics") or {}).get("profile_tables")) or []
    if not tables:
        sheet.append(["No profile table was planned."])
        return
    for table in tables:
        sheet.append([table.get("variable"), table.get("kind")])
        columns = list(table.get("columns") or [])
        sheet.append(["Row", *columns])
        for row in table.get("rows") or []:
            values = row.get("values") or {}
            sheet.append([row.get("label"), *[values.get(column) for column in columns]])
        sheet.append([])


def _impute_rows(result: dict[str, Any]) -> list[list[Any]]:
    """Return imputation log rows.

    Args:
        result: Computed payload.

    Returns:
        Header plus one row per filled column.
    """
    rows: list[list[Any]] = [["Variable", "Strategy", "Filled", "Fill value"]]
    for step in (result.get("diagnostics") or {}).get("steps") or []:
        if step.get("kind") != "impute_missing":
            continue
        for item in (step.get("detail") or {}).get("columns") or []:
            rows.append(
                [
                    item.get("variable"),
                    item.get("strategy"),
                    item.get("filled"),
                    item.get("fill_value"),
                ]
            )
    return rows


def _recode_rows(result: dict[str, Any]) -> list[list[Any]]:
    """Return top-box and bottom-box definitions.

    Args:
        result: Computed payload.

    Returns:
        Header plus one row per recoded column.
    """
    rows: list[list[Any]] = [["Variable", "Output", "Rule", "Codes", "Values"]]
    for step in (result.get("diagnostics") or {}).get("steps") or []:
        if step.get("kind") not in {"top_box", "bottom_box"}:
            continue
        for item in (step.get("detail") or {}).get("columns") or []:
            rows.append(
                [
                    item.get("variable"),
                    item.get("output"),
                    item.get("rule"),
                    ", ".join(str(code) for code in item.get("codes") or []),
                    ", ".join(str(value) for value in item.get("values") or []),
                ]
            )
    return rows


def _diagnostic_rows(result: dict[str, Any]) -> list[list[Any]]:
    """Return warnings and the seed.

    Args:
        result: Computed payload.

    Returns:
        Two-column rows.
    """
    rows: list[list[Any]] = [["Field", "Value"], ["seed", result.get("seed")]]
    for warning in result.get("warnings") or []:
        rows.append(["warning", warning])
    return rows


def _rows_sheet(book: Workbook, title: str, rows: list[list[Any]]) -> None:
    """Add a sheet of plain rows.

    Args:
        book: Workbook.
        title: Sheet name.
        rows: Rows, including a header.
    """
    sheet = book.create_sheet(title)
    for row in rows:
        sheet.append(row)
