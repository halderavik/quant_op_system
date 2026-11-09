"""Table rows for an analyst tab plan."""

from typing import Any

from app.engines.tabspec_banners import coerce_code, is_int_code
from app.engines.tabspec_text import format_codes, format_expr
from app.schemas.expression import Expr
from app.schemas.questionnaire import Question
from app.schemas.tabspec import Banner, DerivedVariable, SignificanceSpec, TableBase, TableSpec

_SIG = SignificanceSpec(enabled=True, alpha=0.05, secondary_alpha=0.10, minimum_effective_base=20)


def _closed(
    question: Question,
    variable_names: list[str],
    section: str,
    by_name: dict[str, dict[str, Any]],
    banners: list[Banner],
    tables: list[TableSpec],
) -> None:
    """Add one Single, Multi, or numeric table.

    Args:
        question: Closed question.
        variable_names: Resolved names.
        section: Module title.
        by_name: Variable dictionary.
        banners: Banner groups.
        tables: Accumulator.
    """
    plan_type = "Multi" if question.type == "multi_select" else "Single"
    table_type = (
        "multiple_response"
        if plan_type == "Multi"
        else ("numeric" if question.type == "numeric" else "categorical")
    )
    info = by_name.get(variable_names[0], {}) if variable_names else {}
    top, bottom, instruction = _scale_boxes(question, info)
    base_text, filt = _base(question)
    stub = variable_names[0] if len(variable_names) == 1 else ", ".join(variable_names)
    tables.append(
        _table(
            len(tables) + 1,
            question.text,
            variable_names or [question.id],
            section=section,
            plan_type=plan_type,
            table_type=table_type,
            banners=banners,
            stub=stub,
            instruction=instruction,
            base_text=base_text,
            base_filter=filt,
            top=top,
            bottom=bottom,
        )
    )


def _grid(
    question: Question,
    variable_names: list[str],
    section: str,
    banners: list[Banner],
    tables: list[TableSpec],
) -> None:
    """Add a grid summary plus one item table per statement.

    Args:
        question: Grid question.
        variable_names: Item variables.
        section: Module title.
        banners: Banner groups.
        tables: Accumulator.
    """
    names = variable_names or [question.id]
    base_text, filt = _base(question)
    tables.append(
        _table(
            len(tables) + 1,
            question.text,
            names,
            section=section,
            plan_type="Grid summary",
            table_type="grid",
            banners=banners,
            method="battery_means / top2box",
            instruction="Rows = items; cells = top-2 box and mean",
            base_text=base_text,
            base_filter=filt,
        )
    )
    for name in names:
        tables.append(
            _table(
                len(tables) + 1,
                f"{question.text} — {name}",
                [name],
                section=section,
                plan_type="Grid item",
                table_type="categorical",
                banners=banners,
                instruction="All codes",
                base_text=base_text,
                base_filter=filt,
            )
        )


def _rank(
    question: Question,
    variable_names: list[str],
    section: str,
    banners: list[Banner],
    tables: list[TableSpec],
    derived: list[DerivedVariable],
) -> None:
    """Add rank-1 and top-3 flags, and a ranking table of the rank-1 flags.

    Args:
        question: Rank question.
        variable_names: Item variables.
        section: Module title.
        banners: Banner groups.
        tables: Accumulator.
        derived: Accumulator.
    """
    flags: list[str] = []
    for source in variable_names or [question.id]:
        rank_one = f"{source}_R1"
        top_three = f"{source}_T3"
        derived.append(
            DerivedVariable(
                name=rank_one,
                recipe="net_flag",
                source=source,
                params={"codes": [1]},
                kind="Ranking flag",
                definition=f"1 if {source} = 1, else 0",
                purpose="Ranked #1 tables",
            )
        )
        derived.append(
            DerivedVariable(
                name=top_three,
                recipe="net_flag",
                source=source,
                params={"codes": [1, 2, 3]},
                kind="Ranking flag",
                definition=f"1 if {source} is answered (1–3), else 0",
                purpose="Top-3 tables",
            )
        )
        flags.append(rank_one)
    base_text, filt = _base(question)
    tables.append(
        _table(
            len(tables) + 1,
            question.text,
            flags,
            section=section,
            plan_type="Ranking",
            table_type="multiple_response",
            banners=banners,
            stub=question.id,
            method="crosstab_sig (derived)",
            instruction="Ranked #1. Top-3 flags are on Derived variables.",
            base_text=base_text,
            base_filter=filt,
        )
    )


def _table(
    number: int,
    title: str,
    names: list[str],
    *,
    banners: list[Banner],
    section: str = "",
    plan_type: str = "Single",
    table_type: str = "categorical",
    stub: str = "",
    method: str = "crosstab_sig",
    instruction: str = "All codes",
    base_text: str = "All",
    base_filter: Expr | None = None,
    top: list[Any] | None = None,
    bottom: list[Any] | None = None,
) -> TableSpec:
    """Build one table row and assign banner plans that do not contain the stub.

    Args:
        number: 1-based position. The id is ``T{number}``.
        title: Question or variable text.
        names: Row variables.
        banners: Banner groups.
        section: Module title.
        plan_type: Analyst type word.
        table_type: Engine type.
        stub: Variable cell. Defaults to the names.
        method: Run method.
        instruction: Rows / nets / stats cell.
        base_text: Base cell.
        base_filter: Parsed filter.
        top: Top-box codes.
        bottom: Bottom-box codes.

    Returns:
        Table spec.
    """
    plans = _plans_for(names, banners) if plan_type not in {"Open end", "Grid summary"} else []
    return TableSpec(
        id=f"T{number}",
        title=title,
        section=section,
        row_variable_names=names,
        stub_label=stub or ", ".join(names),
        table_type=table_type,  # type: ignore[arg-type]
        plan_type=plan_type,
        banner_plans=plans,
        banner_ids=[banner.id for banner in banners if banner.plan in plans],
        base=TableBase(filter=base_filter),
        base_text=base_text,
        row_instruction=instruction,
        method=method,
        significance=_SIG if method.startswith("crosstab_sig") else SignificanceSpec(),
        top_box_codes=top or [],
        bottom_box_codes=bottom or [],
        order=number,
    )


def _plans_for(names: list[str], banners: list[Banner]) -> list[str]:
    """Use the banner plans that do not already contain this stub.

    Args:
        names: Stub variables, including derived flag names.
        banners: Banner groups.

    Returns:
        ``A``, ``B``, both, or neither when the stub is itself the only plan.
    """
    present: list[str] = []
    for plan in ("A", "B"):
        if any(banner.plan == plan for banner in banners) and plan not in present:
            present.append(plan)
    occupied = {
        banner.plan
        for banner in banners
        if banner.variable_name in names or banner.source_variable in names
    }
    return [plan for plan in present if plan not in occupied]


def _scale_boxes(question: Question, info: dict[str, Any]) -> tuple[list[Any], list[Any], str]:
    """Add top-2 and bottom-2 only for an ordered rating scale.

    Args:
        question: Question.
        info: Matching variable, when loaded.

    Returns:
        Top codes, bottom codes, and the rows instruction.
    """
    codes = [option.code for option in question.options] or [
        coerce_code(code) for code in (info.get("value_labels") or {})
    ]
    numbers = [int(code) for code in codes if is_int_code(code)]
    if question.type != "rating" or len(numbers) < 4:
        return [], [], "All codes"
    ordered = sorted(set(numbers))
    bottom = ordered[:2]
    top = ordered[-2:]
    return (
        top,
        bottom,
        (f"All codes; Top-2 ({format_codes(top)}); Bottom-2 ({format_codes(bottom)})"),
    )


def _base(question: Question) -> tuple[str, Expr | None]:
    """Turn a display rule into a base sentence and filter.

    Args:
        question: Question.

    Returns:
        Base text and the same expression used as the table filter.
    """
    if question.display_if is None:
        return "All", None
    return format_expr(question.display_if), question.display_if


closed_table = _closed
grid_tables = _grid
rank_tables = _rank
simple_table = _table
