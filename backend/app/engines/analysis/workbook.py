"""Excel workbook for one analysis run."""

from io import BytesIO
from typing import Any

from openpyxl import Workbook

from app.schemas.analysis import AnalysisReport, AnalysisWorkflow


def workbook_bytes(
    workflow: AnalysisWorkflow,
    result: dict[str, Any],
    report: AnalysisReport,
    images: list[tuple[str, bytes]] | None = None,
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
    _quality_sheet(book, workflow, result)
    _sample_sheet(book, result)
    _rows_sheet(book, "Imputation", _impute_rows(result))
    _rows_sheet(book, "Recodes", _recode_rows(result))
    _method_sheet(book, result)
    _ranking_sheet(book, result)
    _profile_sheet(book, result)
    _compare_sheet(book, result)
    _rows_sheet(book, "Diagnostics", _diagnostic_rows(result))
    _chart_sheet(book, images or [])
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


def _chart_sheet(book: Workbook, images: list[tuple[str, bytes]]) -> None:
    """Place each chart image under its title, one below the other."""
    if not images:
        return
    from openpyxl.drawing.image import Image

    sheet = book.create_sheet("Charts")
    row = 1
    for title, data in images:
        sheet.cell(row=row, column=1, value=title)
        picture = Image(BytesIO(data))
        scale = min(1.0, 900 / max(picture.width, 1))
        picture.width, picture.height = int(picture.width * scale), int(picture.height * scale)
        sheet.add_image(picture, f"A{row + 1}")
        row += int(picture.height / 20) + 4


def _quality_sheet(book: Workbook, workflow: AnalysisWorkflow, result: dict[str, Any]) -> None:
    """Write the research standards and every pass or flag check.

    Args:
        book: Workbook.
        workflow: Plan that ran, with any standards the server applied.
        result: Computed payload.
    """
    diagnostics = result.get("diagnostics") or {}
    sheet = book.create_sheet("Quality checks")
    sheet.append(["Area", "Check", "Status", "Detail"])
    for item in diagnostics.get("quality_checks") or []:
        sheet.append(
            [
                item.get("area"),
                item.get("check"),
                str(item.get("status", "")).upper(),
                item.get("detail"),
            ]
        )
    sheet.append([])
    sheet.append(["Research standards"])
    for line in [*workflow.standards, *(diagnostics.get("standards") or [])]:
        sheet.append([line])


def _ranking_sheet(book: Workbook, result: dict[str, Any]) -> None:
    """Write each driver importance ranking, one block per fit.

    Args:
        book: Workbook.
        result: Computed payload.
    """
    blocks = importance_rankings(result)
    if not blocks:
        return
    sheet = book.create_sheet("Driver importance")
    for name, ranking in blocks:
        sheet.append([name])
        sheet.append(["Rank", "Driver", "Importance %", "Standardized coefficient"])
        for row in ranking:
            sheet.append(
                [
                    row.get("rank"),
                    row.get("driver"),
                    row.get("importance_pct"),
                    row.get("standardized_coefficient"),
                ]
            )
        sheet.append([])


def importance_rankings(result: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    """Return (fit name, ranking) pairs from a single or multi-fit payload.

    Args:
        result: Computed payload.

    Returns:
        Rankings in payload order.
    """
    descriptive = result.get("descriptive") or {}
    if descriptive.get("importance_ranking"):
        return [("Key drivers", descriptive["importance_ranking"])]
    return [
        (name, block["importance_ranking"])
        for name, block in descriptive.items()
        if isinstance(block, dict) and block.get("importance_ranking")
    ]


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
        if step.codes:
            settings.append("codes=" + ",".join(step.codes))
        if step.split_by:
            settings.append(f"separately by {step.split_by}")
        if step.output:
            settings.append(f"output={step.output}")
        for band in step.bands:
            rule = ",".join(band.codes) if band.codes else f"{band.lower}-{band.upper}"
            settings.append(f"{band.label}: {rule}")
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


def _compare_sheet(book: Workbook, result: dict[str, Any]) -> None:
    """Write subgroup comparisons, one block per split method.

    Args:
        book: Workbook.
        result: Computed payload.
    """
    comparisons = ((result.get("diagnostics") or {}).get("comparisons")) or []
    if not comparisons:
        return
    sheet = book.create_sheet("Group comparison")
    for block in comparisons:
        groups = list(block.get("groups") or [])
        bases = block.get("bases") or {}
        sheet.append([f"{block.get('method')} separately by {block.get('split_by')}"])
        two = len(groups) == 2
        sheet.append(
            ["Term", "Field", *groups, *([f"{groups[1]} minus {groups[0]}"] if two else [])]
        )
        sheet.append(["Base", "valid n", *[bases.get(group) for group in groups]])
        for row in block.get("rows") or []:
            values = row.get("values") or {}
            sheet.append(
                [
                    row.get("term"),
                    row.get("field"),
                    *[values.get(group) for group in groups],
                    *([row.get("difference")] if two else []),
                ]
            )
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
