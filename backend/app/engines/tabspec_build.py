"""Build a whole-study tab spec in the analyst-plan style."""

from typing import Any

import pandas as pd

from app.engines.tabspec_banners import build_banner_plan, is_weight_name
from app.engines.tabspec_rows import closed_table, grid_tables, rank_tables, simple_table
from app.schemas.questionnaire import Question, Questionnaire
from app.schemas.tabspec import (
    Banner,
    DerivedVariable,
    MappingItem,
    StudyDefaults,
    TableSpec,
    TabSpec,
)
from app.util import new_id

_CLOSED = {
    "single_select",
    "multi_select",
    "rating",
    "numeric",
    "matrix",
    "grid",
    "rank",
    "screener",
}
_ADMIN_EXACT = {
    "record",
    "uuid",
    "respondent_id",
    "respid",
    "date",
    "start_date",
    "markers",
    "status",
    "survey_version",
    "vlist",
    "list",
    "source",
    "declang",
    "vos",
    "vbrowser",
    "vmobiledevice",
    "vmobileos",
    "useragent",
    "relsk",
    "url",
    "session",
    "igmrid",
    "vdropout",
    "speeder",
    "qtime",
    "sl_count",
    "sl_shown",
}


def build_tabspec(
    questionnaire: Questionnaire | None,
    variables: list[dict[str, Any]] | None,
    *,
    dataset_id: str | None = None,
    questionnaire_ref: dict[str, Any] | None = None,
    weight_variable: str | None = None,
    frame: pd.DataFrame | None = None,
) -> TabSpec:
    """Create an analyst-style spec. Dataset names are never guessed.

    Args:
        questionnaire: Active questionnaire, if any.
        variables: Dataset dictionary, if a dataset is loaded.
        dataset_id: Dataset id.
        questionnaire_ref: Artifact id and version the spec was built from.
        weight_variable: Optional confirmed weight. It is not inferred as a silent default
            unless the caller passes it.
        frame: Respondent data, used for column bases and small-cell collapses.

    Returns:
        Tab spec with banner plans, table rows, derived variables, and a not-tabbed list.
    """
    by_name = {item["name"]: item for item in (variables or [])}
    questions = list(questionnaire.questions) if questionnaire else []
    module_of = _modules(questionnaire)
    banners, derived = build_banner_plan(questions, module_of, by_name, frame)
    tables: list[TableSpec] = []
    exclusions: list[dict[str, str]] = []
    mappings = []
    used: set[str] = set()
    if weight_variable:
        used.add(weight_variable)
    if questionnaire is not None:
        _from_questions(
            questions, module_of, by_name, banners, tables, derived, exclusions, mappings, used
        )
    elif variables is not None:
        _from_variables(variables, banners, tables, exclusions, used, frame)
    if variables is not None:
        _not_tabbed(variables, used, exclusions, frame)
    sample = int(len(frame)) if frame is not None else None
    return TabSpec(
        spec_id=new_id(),
        questionnaire_revision=questionnaire_ref,
        dataset_id=dataset_id,
        study_defaults=StudyDefaults(
            weight_variable=weight_variable,
            minimum_unweighted_base_for_display=20,
            study_title=questionnaire.title if questionnaire else "",
            sample_size=sample,
            sample_note=f"n = {sample}" if sample is not None else "",
        ),
        banners=banners,
        tables=tables,
        derived_variables=derived,
        unresolved_mappings=[item for item in mappings if item.status != "mapped"],
        exclusions=exclusions,
    )


def _from_questions(
    questions: list[Question],
    module_of: dict[str, str],
    by_name: dict[str, dict[str, Any]],
    banners: list[Banner],
    tables: list[TableSpec],
    derived: list[DerivedVariable],
    exclusions: list[dict[str, str]],
    mappings: list[Any],
    used: set[str],
) -> None:
    """Add one plan row, or a grid family, for each question.

    Args:
        questions: Instrument items.
        module_of: Question id to section title.
        by_name: Variable dictionary.
        banners: Banner groups already chosen.
        tables: Accumulator.
        derived: Accumulator for ranking flags.
        exclusions: Questions that are not tabulated.
        mappings: Question-to-variable links.
        used: Names that should not also appear on Not tabbed.
    """
    names = set(by_name)
    for question in questions:
        section = module_of.get(question.id, "")
        variable_names = [name for name in question.variable_names if not names or name in names]
        if not variable_names and (not names or question.id in names):
            variable_names = [question.id]
        if question.type == "text" or question.unsupported:
            tables.append(
                simple_table(
                    len(tables) + 1,
                    question.text,
                    variable_names or [question.id],
                    section=section,
                    plan_type="Open end",
                    table_type="categorical",
                    banners=banners,
                    method="Coding → crosstab_sig",
                    instruction="Build a codeframe, then tab the coded variable as Multi",
                    base_text="All",
                )
            )
            used.update(variable_names or [question.id])
            continue
        if question.type not in _CLOSED and question.type != "allocation":
            exclusions.append(
                {"question_id": question.id, "reason": f"{question.type} is not tabulated"}
            )
            continue
        if names and not variable_names:
            mappings.append(
                MappingItem(
                    question_id=question.id,
                    status="unresolved",
                    reason="No dataset variable matches this question id or its variable_names",
                )
            )
        elif variable_names:
            mappings.append(
                MappingItem(question_id=question.id, variable_names=variable_names, status="mapped")
            )
        if question.type in {"matrix", "grid"}:
            grid_tables(question, variable_names, section, banners, tables)
        elif question.type == "rank":
            rank_tables(question, variable_names, section, banners, tables, derived)
        else:
            closed_table(question, variable_names, section, by_name, banners, tables)
        used.update(variable_names)


def _from_variables(
    variables: list[dict[str, Any]],
    banners: list[Banner],
    tables: list[TableSpec],
    exclusions: list[dict[str, str]],
    used: set[str],
    frame: pd.DataFrame | None,
) -> None:
    """Tab dataset variables when there is no questionnaire.

    Args:
        variables: Variable dictionary.
        banners: Banner groups.
        tables: Accumulator.
        exclusions: Not-tabbed rows.
        used: Names already assigned.
        frame: Data, used only to notice an empty column.
    """
    for item in variables:
        name = item["name"]
        if name in used or is_weight_name(name) or _is_admin(name) or _is_empty(frame, name):
            continue
        if item.get("is_text"):
            tables.append(
                simple_table(
                    len(tables) + 1,
                    str(item.get("label") or name),
                    [name],
                    plan_type="Open end",
                    table_type="categorical",
                    banners=banners,
                    method="Coding → crosstab_sig",
                    instruction="Build a codeframe, then tab the coded variable as Multi",
                )
            )
        else:
            tables.append(
                simple_table(
                    len(tables) + 1,
                    str(item.get("label") or name),
                    [name],
                    plan_type="Single",
                    table_type="categorical",
                    banners=banners,
                    instruction="All codes",
                )
            )
        used.add(name)


def _not_tabbed(
    variables: list[dict[str, Any]],
    used: set[str],
    exclusions: list[dict[str, str]],
    frame: pd.DataFrame | None,
) -> None:
    """List admin, paradata, and empty fields that are not already on the plan.

    Args:
        variables: Variable dictionary.
        used: Names used as stubs, banners, or weights.
        exclusions: Accumulator.
        frame: Data, used to notice an empty column.
    """
    for item in variables:
        name = item["name"]
        if name in used:
            continue
        if _is_admin(name):
            exclusions.append({"question_id": name, "reason": "Admin / paradata / ids"})
        elif _is_empty(frame, name):
            exclusions.append({"question_id": name, "reason": "Empty (n=0)"})
        elif item.get("is_text"):
            exclusions.append({"question_id": name, "reason": "Text variable with no question"})


def _modules(questionnaire: Questionnaire | None) -> dict[str, str]:
    """Map question ids to module titles.

    Args:
        questionnaire: Instrument, or None.

    Returns:
        Section titles.
    """
    found: dict[str, str] = {}
    if questionnaire is None:
        return found
    for module in questionnaire.modules:
        for question_id in module.question_ids:
            found[question_id] = module.title
    return found


def _is_admin(name: str) -> bool:
    """Return whether a name is admin, paradata, or a sample id.

    Args:
        name: Variable name.

    Returns:
        True for names that belong on Not tabbed.
    """
    folded = name.lower()
    return (
        folded in _ADMIN_EXACT
        or folded.startswith(("hid", "verisoul_", "fp_", "dcua"))
        or "_events" in folded
        or "charspersec" in folded
    )


def _is_empty(frame: pd.DataFrame | None, name: str) -> bool:
    """Return whether a loaded column has no observed values.

    Args:
        frame: Data, or None.
        name: Column name.

    Returns:
        True when every value is missing.
    """
    if frame is None or name not in frame.columns:
        return False
    return bool(frame[name].isna().all())
