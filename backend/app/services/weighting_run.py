"""Weighting builder: propose census targets, let the user edit them, and build the weight.

The plan is the project's ``weighting`` output. Building it writes a new dataset version
with the weight column and makes that column the project weight, so later crosstabs,
tab books, and reports are weighted until the user turns it off.
"""

import re
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.agents.weighting_research import normalize_url, research_targets
from app.config import Settings
from app.engines.weighting import (
    achieved_shares,
    age_bands,
    categories_from_labels,
    efficiency,
    fill_sample_shares,
    rake,
    target_problems,
)
from app.errors import AppError
from app.repositories.records import ArtifactRepository, DatasetRepository, ProjectRepository
from app.schemas.weighting import (
    TargetCategory,
    TargetSource,
    WeightingDimension,
    WeightingPlan,
    WeightResult,
)
from app.services.execute import _active_dataset, load_frame
from app.services.storage import Storage
from app.util import new_id

WEIGHT_COLUMN = "QOS_WEIGHT"
_ARTIFACT = "weighting"
_SCHEMA = "weighting/1"
_UNWEIGHTED = re.compile(r"\bunweighted\b|\bwithout (?:a |the )?weight", re.IGNORECASE)
# (pattern, points, concept). Patterns match whole words, so "state" does not find
# "statement" and "age" does not find "image" or "usage".
_DEMOGRAPHIC = (
    (r"\bage(s|d)?\b", 5, "age"),
    (r"\bgender\b", 5, "gender"),
    (r"\bsex\b", 5, "gender"),
    (r"\bregions?\b", 4, "region"),
    (r"\bwhere do you (currently )?live\b|\bwhere you live\b", 4, "region"),
    (r"\bstates?\b|\bprovinces?\b", 3, "region"),
    (r"\bincome\b", 3, "income"),
    (r"\beducation", 3, "education"),
    (r"\bethnic", 3, "ethnic"),
    (r"\brace\b", 3, "race"),
    (r"\bhispanic\b|\blatino", 3, "hispanic"),
    (r"\bemploy(ment|ed)\b", 2, "employment"),
    (r"\bhousehold\b", 1, "household"),
    (r"\burban\b", 2, "urban"),
    (r"\bcountry\b", 2, "country"),
)
# The usual starting point for a general-population weight.
_DEFAULT_CONCEPTS = {"age", "gender", "region"}
_SKIP_LABELS = 15
# Reason: within this many points a proposal's targets are rescaled to 100; beyond it the
# user sees the sum and fixes it.
_RESCALE_GAP = 2.0


def _latest(db: Session, project_id: str) -> tuple[Any, WeightingPlan | None]:
    """The project's weighting output and its plan, when one exists."""
    revision = ArtifactRepository(db).latest_of_type(project_id, _ARTIFACT)
    if revision is None:
        return None, None
    return revision, WeightingPlan.model_validate(revision.content or {})


def _variables(dataset: Any) -> dict[str, dict[str, Any]]:
    """Dataset variables keyed by name."""
    return {item["name"]: item for item in dataset.variables or []}


def candidate_variables(variables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Closed questions that could be weighted, most demographic-looking first.

    Args:
        variables: Dataset variable entries.

    Returns:
        Entries with ``variable``, ``label``, ``score``, ``concept`` (the demographic it
        looks like, or empty), and ``suggested`` (the best age, gender, and region picks).
    """
    found: list[dict[str, Any]] = []
    for item in variables:
        if item.get("is_text") or item["name"] == WEIGHT_COLUMN:
            continue
        text = f"{item['name']} {item.get('label') or ''}".lower()
        hits = [
            (match.start(), -points, points, concept)
            for pattern, points, concept in _DEMOGRAPHIC
            if (match := re.search(pattern, text))
        ]
        # Reason: the word nearest the start names the question; "children under age 18"
        # is about children, which a later word does not change.
        hits.sort()
        where, _, points, concept = hits[0] if hits else (len(text), 0, 0, "")
        labels = item.get("value_labels") or {}
        # Reason: a typed-in age has no answer labels; it is weighted in age bands.
        if not labels and concept == "age" and _numeric(item):
            pass
        elif not 2 <= len(labels) <= _SKIP_LABELS:
            continue
        found.append(
            {
                "variable": item["name"],
                "label": item.get("label") or "",
                "score": points,
                "concept": concept,
                "suggested": False,
                "_where": where,
            }
        )
    # Reason: on a tie, a label that starts with the word ("Age band") beats one that
    # mentions it later ("Children under age 18").
    found.sort(key=lambda entry: (-entry["score"], entry["_where"]))
    for entry in found:
        entry.pop("_where")
    picked: set[str] = set()
    for entry in found:
        if entry["concept"] in _DEFAULT_CONCEPTS and entry["concept"] not in picked:
            entry["suggested"] = True
            picked.add(entry["concept"])
    return found


def _numeric(variable: dict[str, Any]) -> bool:
    """Whether a variable holds numbers rather than text."""
    kind = str(variable.get("type") or variable.get("dtype") or "").lower()
    return not variable.get("is_text") and not any(word in kind for word in ("str", "text", "obj"))


def _dimension(frame: Any, variable: dict[str, Any]) -> WeightingDimension:
    """A dimension with one category per labelled code (or age band) and its sample share."""
    categories = categories_from_labels(variable)
    if not categories and _numeric(variable):
        categories = age_bands(frame[variable["name"]])
    dimension = WeightingDimension(
        variable=variable["name"],
        label=variable.get("label") or "",
        categories=categories,
    )
    fill_sample_shares(frame, dimension)
    return dimension


def default_population(db: Session, project_id: str) -> str:
    """Who the study represents, from the questionnaire's sample notes when there are any."""
    revision = ArtifactRepository(db).latest_of_type(project_id, "questionnaire")
    if revision is None:
        return ""
    notes = (revision.content or {}).get("sample_notes") or []
    return " ".join(str(note) for note in notes)[:600]


def weighting_state(db: Session, storage: Storage, project_id: str) -> dict[str, Any]:
    """Everything the weighting panel shows.

    Args:
        db: Session.
        storage: Project storage.
        project_id: Project id.

    Returns:
        The plan (or None), candidate variables with sample shares, the project weight,
        and whether the plan was built on another dataset version.
    """
    project = ProjectRepository(db).get(project_id)
    revision, plan = _latest(db, project_id)
    payload: dict[str, Any] = {
        "artifact_id": revision.artifact_id if revision else None,
        "version": revision.version if revision else None,
        "plan": plan.model_dump(mode="json") if plan else None,
        "project_weight": project.default_weight_variable,
        "default_population": default_population(db, project_id),
        "dataset_id": None,
        "candidates": [],
        "stale": False,
    }
    if not project.active_dataset_id:
        return payload
    dataset = _active_dataset(db, project_id)
    frame = load_frame(storage, dataset)
    by_name = _variables(dataset)
    payload["dataset_id"] = dataset.id
    payload["candidates"] = [
        {**entry, **_dimension(frame, by_name[entry["variable"]]).model_dump(mode="json")}
        for entry in candidate_variables(list(by_name.values()))
    ]
    built = plan.result.dataset_id if plan and plan.result else None
    # Reason: a weight built before rows were dropped no longer matches the respondents.
    payload["stale"] = bool(built and built != dataset.id)
    return payload


def _save(
    db: Session,
    project_id: str,
    plan: WeightingPlan,
    *,
    created_by: str,
    expected_version: int | None = None,
) -> Any:
    """Write the plan as a new revision of the project's weighting output."""
    revision, _ = _latest(db, project_id)
    return ArtifactRepository(db).create(
        project_id=project_id,
        artifact_type=_ARTIFACT,
        name="Weighting targets",
        content=plan.model_dump(mode="json"),
        content_schema=_SCHEMA,
        created_by=created_by,
        artifact_id=revision.artifact_id if revision else None,
        expected_version=expected_version,
        validation_status="passed" if plan.status == "built" else "pending",
    )


def _summary(revision: Any, plan: WeightingPlan, text: str) -> dict[str, Any]:
    """A task result the chat and the panel both understand."""
    return {
        "summary": text,
        "status": "completed",
        "artifact_id": revision.artifact_id,
        "version": revision.version,
        "plan": plan.model_dump(mode="json"),
    }


def _merge_proposal(
    proposal: Any,
    found: dict[str, str],
    dimensions: dict[str, WeightingDimension],
    frame: Any,
) -> tuple[list[WeightingDimension], list[TargetSource], list[str]]:
    """Turn the research answer into checked dimensions and sources.

    Codes must exist in the survey; references are verified against the searched pages;
    targets close to 100 are rescaled.

    Args:
        proposal: The research agent's answer.
        found: URL to title for every page the search returned.
        dimensions: Survey dimensions keyed by variable, with sample shares.
        frame: Respondent data.

    Returns:
        Dimensions, sources, and notes for the user.
    """
    seen = {normalize_url(url) for url in found}
    sources: list[TargetSource] = []
    for item in proposal.sources:
        sources.append(
            TargetSource(
                id=item.id,
                title=item.title or found.get(item.url, ""),
                url=item.url,
                publisher=item.publisher,
                year=item.year,
                note=item.note,
                verified=normalize_url(item.url) in seen,
            )
        )
    verified = {source.id for source in sources if source.verified}
    known_ids = {source.id for source in sources}
    notes: list[str] = []
    result: list[WeightingDimension] = []
    for proposed in proposal.dimensions:
        survey = dimensions.get(proposed.variable)
        if survey is None:
            notes.append(f"Skipped {proposed.variable}: it is not one of the chosen variables.")
            continue
        valid_codes = {float(code) for category in survey.categories for code in category.codes}
        categories: list[TargetCategory] = []
        for item in proposed.categories:
            codes = [code for code in item.codes if float(code) in valid_codes]
            if not codes:
                notes.append(f"Skipped '{item.label}' on {proposed.variable}: no matching codes.")
                continue
            cited = [sid for sid in item.source_ids if sid in known_ids]
            note = item.note
            if not any(sid in verified for sid in cited):
                note = (
                    note + " " if note else ""
                ) + "Reference not confirmed by the search; check it."
            categories.append(
                TargetCategory(
                    label=item.label,
                    codes=[int(code) if float(code).is_integer() else code for code in codes],
                    target_share=round(float(item.target_share), 2),
                    origin="census",
                    source_ids=cited,
                    note=note.strip(),
                )
            )
        if not categories:
            continue
        total = sum(category.target_share or 0.0 for category in categories)
        if total and abs(total - 100.0) <= _RESCALE_GAP:
            for category in categories:
                category.target_share = round((category.target_share or 0.0) * 100.0 / total, 2)
        dimension = WeightingDimension(
            variable=survey.variable,
            label=proposed.label or survey.label,
            categories=categories,
            note=proposed.note,
        )
        fill_sample_shares(frame, dimension)
        result.append(dimension)
    return result, sources, notes


async def propose_targets(
    db: Session,
    storage: Storage,
    settings: Settings,
    project_id: str,
    *,
    population: str,
    variables: list[str] | None,
    session_id: str,
    on_stage: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Research census targets for the chosen variables and save them for review.

    Args:
        db: Session.
        storage: Project storage.
        settings: Application settings.
        project_id: Project id.
        population: Who the survey represents.
        variables: Variables to weight on. The most demographic-looking three are used
            when none are named.
        session_id: SDK session id.
        on_stage: Optional progress callback.

    Returns:
        Task summary with the saved plan.

    Raises:
        AppError: No dataset, no usable variables, or the research failed.
    """
    dataset = _active_dataset(db, project_id)
    frame = load_frame(storage, dataset)
    by_name = _variables(dataset)
    population = population.strip() or default_population(db, project_id)
    if not population:
        raise AppError(
            "Tell me who the survey represents, such as 'US adults aged 18 to 65', so I can "
            "look up the right census figures.",
            "missing_population",
        )
    if variables is None:
        # Reason: a chat request may name its variables, as in "weight on Q17 and Q18".
        variables = [name for name in by_name if re.search(rf"\b{re.escape(name)}\b", population)]
    chosen = [name for name in (variables or []) if name in by_name]
    if not chosen:
        chosen = [
            entry["variable"]
            for entry in candidate_variables(list(by_name.values()))
            if entry["suggested"]
        ]
    if not chosen:
        raise AppError(
            "I could not find age, gender, or region questions to weight on. Pick the "
            "variables in the Weighting panel.",
            "missing_roles",
        )
    dimensions = {name: _dimension(frame, by_name[name]) for name in chosen}
    proposal, found, _notes = await research_targets(
        settings,
        population=population,
        dimensions=[item.model_dump(mode="json") for item in dimensions.values()],
        session_id=session_id,
        on_stage=on_stage,
    )
    merged, sources, notes = _merge_proposal(proposal, found, dimensions, frame)
    # Reason: a variable the research had no figure for stays in the plan for the user to fill.
    for name, dimension in dimensions.items():
        if all(item.variable != name for item in merged):
            merged.append(dimension)
            notes.append(f"No published figure was found for {name}; enter its targets yourself.")
    plan = WeightingPlan(
        population=population,
        dataset_id=dataset.id,
        dimensions=merged,
        sources=sources,
        research_note=" ".join([proposal.note, *notes]).strip(),
    )
    revision = _save(db, project_id, plan, created_by="weighting_research")
    confirmed = sum(1 for source in sources if source.verified)
    text = (
        f"Proposed weighting targets for {population} on {', '.join(chosen)}, from "
        f"{len(sources)} source{'s' if len(sources) != 1 else ''} ({confirmed} confirmed by the "
        "search). Review them in the Weighting tab, change any target, then build the weight."
    )
    return _summary(revision, plan, text)


def save_plan(
    db: Session,
    storage: Storage,
    project_id: str,
    content: dict[str, Any],
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Save the user's edits to the targets. Sample shares are recalculated.

    Args:
        db: Session.
        storage: Project storage.
        project_id: Project id.
        content: Plan as edited in the panel.
        expected_version: Version the edit was made on.

    Returns:
        The saved plan and its version.
    """
    plan = WeightingPlan.model_validate(content)
    dataset = _active_dataset(db, project_id)
    frame = load_frame(storage, dataset)
    for dimension in plan.dimensions:
        if dimension.variable in frame.columns:
            fill_sample_shares(frame, dimension)
    plan.dataset_id = dataset.id
    # Reason: changed targets need a rebuild before the weight matches them again.
    plan.status = "proposed"
    revision = _save(db, project_id, plan, created_by="user", expected_version=expected_version)
    return {
        "artifact_id": revision.artifact_id,
        "version": revision.version,
        "plan": plan.model_dump(mode="json"),
        "problems": target_problems(frame, plan.dimensions),
    }


def build_weight(db: Session, storage: Storage, project_id: str) -> dict[str, Any]:
    """Rake to the saved targets, add the weight to a new dataset version, and use it.

    Args:
        db: Session.
        storage: Project storage.
        project_id: Project id.

    Returns:
        Task summary with the weight report.

    Raises:
        AppError: No plan yet, or the targets cannot be raked.
    """
    revision, plan = _latest(db, project_id)
    if plan is None:
        raise AppError(
            "There are no weighting targets yet. Ask me to propose census targets, or add "
            "them in the Weighting tab.",
            "missing_weighting",
        )
    dataset = _active_dataset(db, project_id)
    frame = load_frame(storage, dataset)
    problems = target_problems(frame, plan.dimensions)
    if problems:
        raise AppError("The weight was not built. " + " ".join(problems), "invalid_targets")
    for dimension in plan.dimensions:
        fill_sample_shares(frame, dimension)
    weights, facts = rake(frame, plan.dimensions, plan.settings)
    weighted = frame.copy()
    weighted[WEIGHT_COLUMN] = weights.round(6)
    dataset_id = new_id()
    relative = f"datasets/{dataset_id}.parquet"
    snapshot = storage.resolve(project_id, relative)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    weighted.to_parquet(snapshot)
    names = ", ".join(dimension.variable for dimension in plan.dimensions)
    variables = [item for item in dataset.variables or [] if item["name"] != WEIGHT_COLUMN]
    variables.append(
        {
            "name": WEIGHT_COLUMN,
            "label": f"Rim weight on {names}",
            "kind": "numeric",
            "measurement": "scale",
            "value_labels": {},
            "user_missing_values": [],
            "is_text": False,
        }
    )
    candidates = [name for name in dataset.weight_candidates or [] if name != WEIGHT_COLUMN]
    created = DatasetRepository(db).add(
        id=dataset_id,
        project_id=project_id,
        source_file_id=dataset.source_file_id,
        source_sha256=dataset.source_sha256,
        format=dataset.format,
        row_count=int(len(weighted)),
        variables=variables,
        weight_candidates=[WEIGHT_COLUMN, *candidates],
        version=int(dataset.version) + 1,
        parquet_relpath=relative,
    )
    project = ProjectRepository(db).get(project_id)
    project.active_dataset_id = created.id
    project.default_weight_variable = WEIGHT_COLUMN
    score = efficiency(weights)
    plan.result = WeightResult(
        weight_variable=WEIGHT_COLUMN,
        dataset_id=created.id,
        respondents=int(len(weighted)),
        converged=facts["converged"],
        iterations=facts["iterations"],
        efficiency=round(score, 1),
        effective_base=round(len(weighted) * score / 100.0, 1),
        design_effect=round(100.0 / score, 3) if score else 0.0,
        min_weight=round(float(weights.min()), 3),
        max_weight=round(float(weights.max()), 3),
        capped=facts["capped"],
        achieved=achieved_shares(frame, plan.dimensions, weights),
        warnings=facts["warnings"],
    )
    plan.status = "built"
    plan.dataset_id = created.id
    saved = _save(db, project_id, plan, created_by="weighting")
    result = plan.result
    text = (
        f"Built {WEIGHT_COLUMN} on {names}. Weighting efficiency is {result.efficiency:.1f}% "
        f"(effective base {result.effective_base:,.0f} of {result.respondents:,}), and weights "
        f"run from {result.min_weight:.2f} to {result.max_weight:.2f}. "
        + ("All targets are met. " if result.converged else " ".join(result.warnings) + " ")
        + "Crosstabs, tab books, and reports now use this weight, with significance tested "
        "on the effective base. Turn it off in the Weighting tab for unweighted tables."
    )
    return _summary(saved, plan, text)


def set_weight_use(db: Session, project_id: str, enabled: bool) -> dict[str, Any]:
    """Turn the built weight on or off for later tables.

    Args:
        db: Session.
        project_id: Project id.
        enabled: Use the weight when true.

    Returns:
        The project weight now in use, or None.
    """
    project = ProjectRepository(db).get(project_id)
    if enabled:
        _, plan = _latest(db, project_id)
        if plan is None or plan.result is None:
            raise AppError("Build the weight before turning it on.", "missing_weighting")
        project.default_weight_variable = plan.result.weight_variable
    else:
        project.default_weight_variable = None
    return {"project_weight": project.default_weight_variable}


def project_weight(
    db: Session, project_id: str, explicit: str | None = None, text: str = ""
) -> str | None:
    """The weight a table should use.

    A weight named in the request wins. Asking for unweighted tables uses none. Otherwise
    the project weight is used when the active dataset has that column.

    Args:
        db: Session.
        project_id: Project id.
        explicit: Weight named in the request.
        text: Request text.

    Returns:
        Weight variable, or None.
    """
    if explicit:
        return explicit
    if _UNWEIGHTED.search(text or ""):
        return None
    project = ProjectRepository(db).get(project_id)
    name = project.default_weight_variable
    if not name or not project.active_dataset_id:
        return None
    dataset = DatasetRepository(db).get(project.active_dataset_id)
    return name if name in _variables(dataset) else None
