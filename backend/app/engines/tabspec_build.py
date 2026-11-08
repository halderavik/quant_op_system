"""Build a whole-study tab spec from a questionnaire, a dataset, or both."""

from typing import Any

from app.schemas.questionnaire import Questionnaire
from app.schemas.tabspec import (
    Banner,
    BannerCategory,
    MappingItem,
    SignificanceSpec,
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
_MULTI = {"multi_select"}
_NUMERIC = {"numeric", "rating"}
_PAIRWISE = SignificanceSpec(
    enabled=True,
    alpha=0.05,
    secondary_alpha=0.10,
    correction="none",
    minimum_effective_base=30,
)


def build_tabspec(
    questionnaire: Questionnaire | None,
    variables: list[dict[str, Any]] | None,
    *,
    dataset_id: str | None = None,
    questionnaire_ref: dict[str, Any] | None = None,
    weight_variable: str | None = None,
) -> TabSpec:
    """Create a canonical spec. Dataset names are never guessed.

    Args:
        questionnaire: Active questionnaire, if any.
        variables: Dataset dictionary, if a dataset is loaded.
        dataset_id: Dataset id.
        questionnaire_ref: Artifact id and version the spec was built from.
        weight_variable: Optional confirmed weight. It is not inferred as a silent default
            unless the caller passes it.

    Returns:
        Tab spec with exclusions and unresolved mappings called out.
    """
    names = {item["name"] for item in (variables or [])}
    by_name = {item["name"]: item for item in (variables or [])}
    banners = _banners(by_name)
    tables: list[TableSpec] = []
    exclusions: list[dict[str, str]] = []
    mappings: list[MappingItem] = []
    if questionnaire is not None:
        for position, question in enumerate(questionnaire.questions, start=1):
            if question.type == "text" or question.unsupported:
                exclusions.append(
                    {
                        "question_id": question.id,
                        "reason": "Open text is excluded from crosstabs and belongs in the coding workflow",
                    }
                )
                mappings.append(
                    MappingItem(question_id=question.id, status="excluded", reason="Open text")
                )
                continue
            if question.type not in _CLOSED and question.type != "allocation":
                exclusions.append(
                    {"question_id": question.id, "reason": f"{question.type} is not tabulated"}
                )
                continue
            variable_names = [name for name in question.variable_names if name in names]
            if not variable_names and question.id in names:
                variable_names = [question.id]
            if variables is not None and not variable_names:
                mappings.append(
                    MappingItem(
                        question_id=question.id,
                        status="unresolved",
                        reason="No dataset variable matches this question id or its variable_names",
                    )
                )
            elif variable_names:
                mappings.append(
                    MappingItem(
                        question_id=question.id, variable_names=variable_names, status="mapped"
                    )
                )
            table_type = (
                "multiple_response"
                if question.type in _MULTI
                else ("numeric" if question.type in _NUMERIC else "categorical")
            )
            tables.append(
                TableSpec(
                    id=f"T{position:03d}",
                    title=question.text[:120],
                    row_variable_names=variable_names or [question.id],
                    table_type=table_type,  # type: ignore[arg-type]
                    banner_ids=[banner.id for banner in banners],
                    weight_variable=weight_variable,
                    significance=_PAIRWISE,
                    order=position,
                )
            )
    elif variables is not None:
        position = 1
        for item in variables:
            if item.get("is_text"):
                exclusions.append(
                    {"question_id": item["name"], "reason": "Text variable excluded from tabs"}
                )
                continue
            if (
                item["name"] in {banner.variable_name for banner in banners}
                or "weight" in item["name"].lower()
            ):
                exclusions.append(
                    {
                        "question_id": item["name"],
                        "reason": "Used as a banner or weight, not a stub",
                    }
                )
                continue
            tables.append(
                TableSpec(
                    id=f"T{position:03d}",
                    title=str(item.get("label") or item["name"]),
                    row_variable_names=[item["name"]],
                    table_type="categorical",
                    banner_ids=[banner.id for banner in banners],
                    weight_variable=weight_variable,
                    significance=_PAIRWISE,
                    order=position,
                )
            )
            position += 1
    return TabSpec(
        spec_id=new_id(),
        questionnaire_revision=questionnaire_ref,
        dataset_id=dataset_id,
        study_defaults=StudyDefaults(weight_variable=weight_variable),
        banners=banners,
        tables=tables,
        unresolved_mappings=[item for item in mappings if item.status != "mapped"],
        exclusions=exclusions,
    )


def _banners(by_name: dict[str, dict[str, Any]]) -> list[Banner]:
    """Build banners only for demographic variables that actually exist.

    Args:
        by_name: Variable dictionary.

    Returns:
        Banners. Empty when the dataset has no recognised banner variables.
    """
    banners: list[Banner] = []
    for name, label in (("gender", "Gender"), ("age_band", "Age"), ("age", "Age")):
        if name not in by_name or any(banner.variable_name == name for banner in banners):
            continue
        info = by_name[name]
        categories = []
        for order, (code, text) in enumerate((info.get("value_labels") or {}).items()):
            categories.append(BannerCategory(label=str(text), codes=[_coerce(code)], order=order))
        if not categories and name == "gender":
            continue
        banners.append(
            Banner(
                id=f"bn_{name}",
                label=label,
                variable_name=name,
                categories=categories,
                include_total=True,
            )
        )
    return banners


def _coerce(code: str) -> Any:
    """Convert a value-label key back to a number when it is numeric.

    Args:
        code: Label key stored as text.

    Returns:
        Int, float, or the original text.
    """
    try:
        number = float(code)
    except ValueError:
        return code
    if number.is_integer():
        return int(number)
    return number
