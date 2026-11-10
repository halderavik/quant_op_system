"""Turn a validator plan into a tab spec the crosstab engine can run."""

from typing import Any

import pandas as pd

from app.engines.crosstab import run_table
from app.engines.derived import apply_derived, in_codes
from app.engines.expression import mask_frame
from app.engines.tabspec_banners import _collapse, _letter, is_int_code
from app.engines.tabspec_profile import ColumnProfile, DatasetProfile
from app.engines.tabspec_text import format_codes, low_base_flag, parse_base
from app.errors import AppError
from app.schemas.tabspec import (
    Banner,
    BannerCategory,
    DerivedVariable,
    NetSpec,
    PlanTable,
    SignificanceSpec,
    StudyDefaults,
    TableBase,
    TableSpec,
    TabSpec,
    TabulationPlan,
)
from app.util import new_id

_SIG = SignificanceSpec(enabled=True, alpha=0.05, secondary_alpha=0.10, minimum_effective_base=20)
_RUNNABLE = {"single": "categorical", "multi": "multiple_response", "numeric": "numeric"}


def compile_tabulation(
    plan: TabulationPlan,
    profile: DatasetProfile,
    frame: pd.DataFrame,
    *,
    dataset_id: str | None,
    questionnaire_ref: dict[str, Any] | None,
    weight_variable: str | None,
    study_title: str,
) -> tuple[TabSpec | None, list[str]]:
    """Build a tab spec from validator decisions and the column profile.

    Args:
        plan: Banners, tables, and exclusions from the validator.
        profile: Columns the validator was allowed to name.
        frame: Respondent data, used for bases and for dropping an empty filter.
        dataset_id: Dataset id stored on the spec.
        questionnaire_ref: Questionnaire artifact id and version.
        weight_variable: Confirmed weight column, when it is in the data.
        study_title: Study title for the plan overview.

    Returns:
        A spec when every name and punch is usable, and the reasons it is not.
    """
    columns = {item.name: item for item in profile.columns}
    issues: list[str] = []
    if not plan.tables:
        issues.append("The plan has no tables to run.")
    banners, derived, banner_issues = _banners(plan, columns, frame)
    issues.extend(banner_issues)
    tables: list[TableSpec] = []
    for index, item in enumerate(plan.tables, start=1):
        table, table_issues = _table(index, item, columns, banners, frame)
        issues.extend(table_issues)
        if table is not None:
            tables.append(table)
    if issues:
        return None, issues
    weight = weight_variable if weight_variable and weight_variable in frame.columns else None
    spec = TabSpec(
        spec_id=new_id(),
        questionnaire_revision=questionnaire_ref,
        dataset_id=dataset_id,
        study_defaults=StudyDefaults(
            weight_variable=weight,
            minimum_unweighted_base_for_display=20,
            study_title=study_title,
            sample_size=int(len(frame)),
            sample_note=f"n = {len(frame)}",
        ),
        banners=banners,
        tables=tables,
        derived_variables=derived,
        exclusions=[
            {"question_id": item.name, "reason": item.reason or "Not tabulated"}
            for item in plan.exclusions
        ],
    )
    return spec, []


def execution_issues(
    spec: TabSpec, frame: pd.DataFrame, variables: list[dict[str, Any]]
) -> list[str]:
    """Dry-run every table and report a base or a code list the engine cannot count.

    Args:
        spec: Compiled spec.
        frame: Respondent data.
        variables: Variable dictionary.

    Returns:
        One message per table that would be empty. An empty list means each table has a base.
    """
    try:
        prepared = apply_derived(frame, spec.derived_variables)
    except AppError as exc:
        return [exc.message]
    issues: list[str] = []
    for table in spec.tables:
        try:
            result = run_table(prepared, variables, table, spec.study_defaults, spec.banners)
        except AppError as exc:
            issues.append(f"{table.id} {table.title}: {exc.message}")
            continue
        issues.extend(_empty(table, result))
    return issues


def _banners(
    plan: TabulationPlan, columns: dict[str, ColumnProfile], frame: pd.DataFrame
) -> tuple[list[Banner], list[DerivedVariable], list[str]]:
    """Build banner groups from the plan and the observed codes.

    Args:
        plan: Validator plan.
        columns: Profile keyed by name.
        frame: Respondent data.

    Returns:
        Banners, collapse variables, and problems.
    """
    banners: list[Banner] = []
    derived: list[DerivedVariable] = []
    issues: list[str] = []
    letters = {"A": 0, "B": 0}
    seen: set[str] = set()
    for item in plan.banners:
        column = columns.get(item.variable_name)
        if column is None:
            issues.append(f"Banner variable '{item.variable_name}' is not in the dataset profile.")
            continue
        if column.shape != "single" or column.nonmissing_n == 0:
            issues.append(
                f"Banner '{item.variable_name}' is {column.shape} and cannot be a banner column."
            )
            continue
        if item.variable_name in seen:
            issues.append(f"Banner '{item.variable_name}' is listed more than once.")
            continue
        seen.add(item.variable_name)
        codes, code_issue = _chosen_codes(item.variable_name, item.codes, column, "Banner")
        if code_issue:
            issues.append(code_issue)
            continue
        banner, extra = _one_banner(
            item.plan, item.variable_name, item.label or column.label, codes, column, frame, letters
        )
        banners.append(banner)
        if extra is not None:
            derived.append(extra)
    return banners, derived, issues


def _one_banner(
    plan: str,
    name: str,
    label: str,
    codes: list[int],
    column: ColumnProfile,
    frame: pd.DataFrame,
    letters: dict[str, int],
) -> tuple[Banner, DerivedVariable | None]:
    """Build one banner, collapsing categories under n=20 when a larger one remains.

    Args:
        plan: A or B.
        name: Source variable.
        label: Banner label.
        codes: Codes to keep.
        column: Profile entry, used for value labels.
        frame: Respondent data.
        letters: Next letter index per plan.

    Returns:
        Banner and an optional derived collapse.
    """
    categories: list[BannerCategory] = []
    for order, code in enumerate(codes):
        text = column.value_labels.get(str(code), str(code))
        count = int(in_codes(frame[name], [code]).sum()) if name in frame.columns else 0
        categories.append(
            BannerCategory(
                label=text,
                codes=[code],
                order=order,
                n=count,
                low_base=low_base_flag(count),
            )
        )
    variable_name = name
    note = f"{name} (as is)"
    derived = None
    small = [item for item in categories if item.n is not None and item.n < 20]
    if (
        small
        and len(small) < len(categories)
        and all(is_int_code(item.codes[0]) for item in categories)
    ):
        variable_name, note, categories, derived = _collapse(name, categories, small)
    for category in categories:
        category.letter = _letter(letters, plan)
        if not category.definition:
            category.definition = f"{variable_name} = {format_codes(category.codes)}"
    group = f"{label} ({name})" if label != name else name
    banner = Banner(
        id=f"{plan}_{name}",
        label=group,
        group=group,
        plan=plan,
        variable_name=variable_name,
        source_variable=name,
        variable_note=note,
        categories=categories,
        include_total=True,
    )
    return banner, derived


def _table(
    number: int,
    item: PlanTable,
    columns: dict[str, ColumnProfile],
    banners: list[Banner],
    frame: pd.DataFrame,
) -> tuple[TableSpec | None, list[str]]:
    """Build one table row, or report why its variables cannot be tabulated.

    Args:
        number: 1-based position.
        item: Validator table decision.
        columns: Profile keyed by name.
        banners: Banners already compiled.
        frame: Respondent data, used to drop a filter that keeps nobody.

    Returns:
        Table spec and problems. The spec is omitted when a problem blocks it.
    """
    issues: list[str] = []
    if not item.row_variable_names:
        return None, [f"'{item.title}' has no row variables."]
    profiles = []
    for name in item.row_variable_names:
        column = columns.get(name)
        if column is None:
            issues.append(f"Variable '{name}' is not in the dataset profile.")
            continue
        if column.shape not in _RUNNABLE or column.nonmissing_n == 0:
            issues.append(f"Variable '{name}' is {column.shape} and is not a crosstab stub.")
            continue
        profiles.append(column)
    if issues:
        return None, issues
    expected = _RUNNABLE[profiles[0].shape]
    if any(_RUNNABLE[column.shape] != item.table_type for column in profiles):
        issues.append(f"'{item.title}' is {item.table_type}, but the columns are {expected}.")
    if item.table_type != "multiple_response" and len(item.row_variable_names) != 1:
        issues.append(f"'{item.title}' uses one column.")
    selected = list(item.selected_codes)
    if item.table_type == "multiple_response":
        selected, punch_issue = _punch(item.title, selected, profiles)
        if punch_issue:
            issues.append(punch_issue)
    if issues:
        return None, issues
    base_text, base_filter, notes = _base(item.base, frame)
    plans = list(item.banner_plans) or ["A", "B"]
    names = list(item.row_variable_names)
    banner_ids = [
        banner.id
        for banner in banners
        if banner.plan in plans
        and banner.variable_name not in names
        and banner.source_variable not in names
    ]
    used_plans = [banner.plan for banner in banners if banner.id in banner_ids]
    table = TableSpec(
        id=f"T{number}",
        title=item.title,
        section=item.section,
        row_variable_names=names,
        selected_codes=selected if item.table_type == "multiple_response" else [],
        stub_label=", ".join(names),
        table_type=item.table_type,
        plan_type="Multi" if item.table_type == "multiple_response" else "Single",
        banner_plans=[plan for plan in ("A", "B") if plan in used_plans],
        banner_ids=banner_ids,
        base=TableBase(filter=base_filter),
        base_text=base_text,
        row_instruction=_instruction(item, selected),
        method="crosstab_sig",
        significance=_SIG,
        nets=[
            NetSpec(
                id=f"N{index}",
                label=net.label,
                child_codes=list(net.child_codes),
                child_variables=list(net.child_variables),
            )
            for index, net in enumerate(item.nets, start=1)
        ],
        top_box_codes=list(item.top_box_codes),
        bottom_box_codes=list(item.bottom_box_codes),
        notes=notes,
        order=number,
    )
    return table, []


def _punch(
    title: str, selected: list[int], columns: list[ColumnProfile]
) -> tuple[list[int], str | None]:
    """Keep a punch only when that code is in the data.

    Args:
        title: Table title, used in the problem text.
        selected: Punch codes from the validator.
        columns: Row profiles.

    Returns:
        Codes to store, and a problem when none of them occur.
    """
    observed: set[int] = set()
    for column in columns:
        observed.update(_ints(column.observed_codes))
    if not selected:
        if 1 in observed:
            return [1], None
        return [], f"'{title}' needs selected_codes. Code 1 is not in the data."
    missing = [code for code in selected if code not in observed]
    if missing:
        return [], (
            f"'{title}' selected {format_codes(missing)}, which does not appear in the row columns."
        )
    return selected, None


def _chosen_codes(
    name: str, requested: list[int], column: ColumnProfile, kind: str
) -> tuple[list[int], str | None]:
    """Intersect requested codes with the codes that occur.

    Args:
        name: Variable name.
        requested: Codes the validator asked to keep. Empty means every observed code.
        column: Profile entry.
        kind: ``Banner`` or another label for the problem text.

    Returns:
        Codes to use, and a problem when none remain.
    """
    observed = _ints(column.observed_codes)
    if not observed:
        return [], f"{kind} '{name}' has no observed codes."
    if not requested:
        return observed, None
    kept = [code for code in requested if code in observed]
    if not kept:
        return [], f"{kind} '{name}' codes {format_codes(requested)} do not appear in the data."
    return kept, None


def _base(text: str, frame: pd.DataFrame) -> tuple[str, Any, list[str]]:
    """Use a code comparison only when it keeps respondents.

    Args:
        text: Base sentence from the validator.
        frame: Respondent data.

    Returns:
        Base text, filter, and notes. A filter that matches nobody becomes ``All``.
    """
    expr, confirmed = parse_base(text)
    if not confirmed or expr is None:
        note = (
            []
            if (text or "").strip().lower() in {"", "all"}
            else ["The base was not a code comparison, so the table uses All."]
        )
        return "All", None, note
    if expr.ref not in frame.columns:
        return (
            "All",
            None,
            [f"The base names '{expr.ref}', which is not a column, so the table uses All."],
        )
    try:
        mask = mask_frame(expr, frame)
    except AppError:
        return "All", None, ["The base could not be applied, so the table uses All."]
    if int(mask.sum()) == 0:
        return "All", None, ["The base matched no respondents, so the table uses All."]
    return text.strip(), expr, []


def _instruction(item: PlanTable, selected: list[int]) -> str:
    """Write the rows cell, including the punch the engine will count.

    Args:
        item: Validator table decision.
        selected: Punch codes stored on a multiple-response table.

    Returns:
        Rows cell text.
    """
    parts = ["All codes"]
    if item.table_type == "multiple_response" and selected:
        parts = [f"Selected ({format_codes(selected)})"]
    if item.top_box_codes:
        parts.append(f"Top-2 ({format_codes(item.top_box_codes)})")
    if item.bottom_box_codes:
        parts.append(f"Bottom-2 ({format_codes(item.bottom_box_codes)})")
    for net in item.nets:
        if net.child_codes:
            parts.append(f"NET {net.label} ({format_codes(net.child_codes)})")
    return "; ".join(parts)


def _empty(table: TableSpec, result: Any) -> list[str]:
    """Report a table whose Total base or category counts are empty.

    Args:
        table: Table that was run.
        result: Engine result.

    Returns:
        A problem, or an empty list when the table has a base and a count or a mean.
    """
    label = f"{table.id} {table.title}"
    if table.table_type == "numeric":
        mean = next((row for row in result.rows if row.row_kind == "mean"), None)
        if mean is None or "total" not in mean.cells:
            return [f"{label}: the table has no mean row."]
        base = mean.cells["total"].unweighted_base or 0
        if base == 0 or mean.cells["total"].estimate is None:
            return [f"{label}: the unweighted Total base is 0."]
        return []
    categories = [row for row in result.rows if row.row_kind == "category"]
    if not categories or "total" not in categories[0].cells:
        return [f"{label}: the table has no rows."]
    base = categories[0].cells["total"].unweighted_base or 0
    if base == 0:
        return [f"{label}: the unweighted Total base is 0."]
    counted = sum(int(row.cells["total"].unweighted_numerator or 0) for row in categories)
    if counted == 0:
        return [
            f"{label}: every category count is 0. The punch or row codes do not match the data."
        ]
    return []


def _ints(codes: list[str]) -> list[int]:
    """Keep integral observed codes.

    Args:
        codes: Code text from the profile.

    Returns:
        Integers, in the same order, without duplicates.
    """
    found: list[int] = []
    for text in codes:
        try:
            number = float(text)
        except (TypeError, ValueError):
            continue
        if number.is_integer():
            code = int(number)
            if code not in found:
                found.append(code)
    return found
