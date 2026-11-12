"""Map a research audience onto Prolific filters that exist in the catalog."""

import re

from pydantic import BaseModel, Field

from app.engines.sample_parse import ParsedAudience
from app.schemas.sample_purchase import AgeBand, AudienceFilter

_REP_TYPES = {
    "UK_REP_SAMPLE",
    "UK_REGIONAL_REP_SAMPLE",
    "REP_SAMPLE_UK_ENGLISH_AGE_POLITICAL_AFFILIATION",
    "US_REP_SAMPLE",
    "US_REGIONAL_REP_SAMPLE",
    "REP_SAMPLE_US_ENGLISH_AGE_POLITICAL_AFFILIATION",
    "REP_SAMPLE_US_ENGLISH_AGE_POLITICAL_AFFILIATION_ETHNICITY",
}
_COUNTRY_ALIASES = {
    "united kingdom": ("united kingdom", "uk", "britain", "great britain"),
    "united states": ("united states", "usa", "us", "u.s.", "america"),
}


class CatalogFilter(BaseModel):
    """One filter from the live catalog."""

    filter_id: str
    title: str
    kind: str
    choices: dict[str, str] = Field(default_factory=dict)


class ProposedFilter(BaseModel):
    """A filter a model suggested. Ids are checked against the catalog."""

    filter_id: str
    selected_labels: list[str] = Field(default_factory=list)
    lower: int | None = None
    upper: int | None = None
    weights: dict[str, float] = Field(default_factory=dict)


class AudienceProposal(BaseModel):
    """Structured audience. Unknown filter ids are rejected before a quote is saved."""

    study_type: str | None = None
    sample_size: int | None = None
    estimated_minutes: int | None = None
    filters: list[ProposedFilter] = Field(default_factory=list)


def catalog_from_payload(payload: dict) -> list[CatalogFilter]:
    """Normalize a filter-list response.

    Args:
        payload: Prolific filter list.

    Returns:
        Catalog rows with string choice labels.
    """
    rows = payload.get("results") if isinstance(payload, dict) else None
    catalog: list[CatalogFilter] = []
    if not isinstance(rows, list):
        return catalog
    for row in rows:
        if not isinstance(row, dict) or not row.get("filter_id"):
            continue
        choices: dict[str, str] = {}
        raw = row.get("choices")
        if isinstance(raw, dict):
            choices = {str(key): str(value) for key, value in raw.items()}
        catalog.append(
            CatalogFilter(
                filter_id=str(row["filter_id"]),
                title=str(row.get("title") or row["filter_id"]),
                kind=str(row.get("type") or "select"),
                choices=choices,
            )
        )
    return catalog


def resolve_audience(
    parsed: ParsedAudience, catalog: list[CatalogFilter]
) -> tuple[list[AudienceFilter], str | None, str]:
    """Turn parsed words into catalog filters.

    Args:
        parsed: Parsed audience.
        catalog: Live filters.

    Returns:
        Filters, representative study type, and a note when a type was not applied.
    """
    study_type = parsed.study_type if parsed.study_type in _REP_TYPES else None
    note = ""
    if study_type and parsed.custom_quota:
        note = (
            "A representative sample was not applied because the request also sets "
            "its own age or sex quotas."
        )
        study_type = None
    if study_type:
        return [], study_type, note
    filters: list[AudienceFilter] = []
    country = _country_filter(parsed.countries, catalog)
    if country:
        filters.append(country)
    age = _age_filter(parsed, catalog)
    if age:
        filters.append(age)
    sex = _sex_filter(parsed.sex, catalog)
    if sex:
        filters.append(sex)
    return filters, None, note


def validate_filters(filters: list[AudienceFilter], catalog: list[CatalogFilter]) -> list[str]:
    """Reject a panel edit that names a filter or choice the catalog does not have.

    Args:
        filters: Filters the panel sent back.
        catalog: Live filters.

    Returns:
        Problems. An empty list means the filters can be priced.
    """
    known = {item.filter_id: item for item in catalog}
    errors: list[str] = []
    for item in filters:
        match = known.get(item.filter_id)
        if match is None:
            errors.append(f"Unknown Prolific filter {item.filter_id}.")
            continue
        if item.kind == "select":
            for choice_id in item.selected_values:
                if choice_id not in match.choices:
                    errors.append(f"{match.title} has no choice {choice_id}.")
    return errors


def filters_from_proposal(
    proposal: AudienceProposal, catalog: list[CatalogFilter]
) -> tuple[list[AudienceFilter], str | None, list[str]]:
    """Accept a model proposal only when every id and label exists.

    Args:
        proposal: Proposed audience.
        catalog: Live filters.

    Returns:
        Filters, study type, and rejection messages. A rejection means the quote is not saved.
    """
    known = {item.filter_id: item for item in catalog}
    errors: list[str] = []
    filters: list[AudienceFilter] = []
    study_type = proposal.study_type if proposal.study_type in _REP_TYPES else None
    if proposal.study_type and study_type is None:
        errors.append(f"Unknown representative sample type {proposal.study_type}.")
    for item in proposal.filters:
        match = known.get(item.filter_id)
        if match is None:
            errors.append(f"Unknown Prolific filter {item.filter_id}.")
            continue
        built, problem = _from_catalog(match, item)
        if problem:
            errors.append(problem)
        elif built is not None:
            filters.append(built)
    return filters, study_type, errors


def _country_filter(countries: list[str], catalog: list[CatalogFilter]) -> AudienceFilter | None:
    """Match country names to a country filter.

    Args:
        countries: Normalized country names.
        catalog: Live filters.

    Returns:
        A select filter, or None when the catalog has no matching choice.
    """
    target = _find(catalog, ("current-country-of-residence", "country-of-residence"), "country")
    if target is None or not countries:
        return None
    selected: list[str] = []
    labels: dict[str, str] = {}
    for country in countries:
        aliases = _COUNTRY_ALIASES.get(country, (country,))
        for choice_id, label in target.choices.items():
            if label.lower() in aliases or any(alias in label.lower() for alias in aliases):
                selected.append(choice_id)
                labels[choice_id] = label
                break
    if not selected:
        return None
    return AudienceFilter(
        filter_id=target.filter_id,
        label=target.title,
        kind="select",
        selected_values=selected,
        choice_labels=labels,
    )


def _age_filter(parsed: ParsedAudience, catalog: list[CatalogFilter]) -> AudienceFilter | None:
    """Build an age range, with bands when the request named more than one.

    Args:
        parsed: Parsed audience.
        catalog: Live filters.

    Returns:
        A range filter, or None.
    """
    if parsed.age is None and not parsed.age_bands:
        return None
    target = _find(catalog, ("age",), "age")
    if target is None or target.kind != "range":
        return None
    if parsed.age_bands:
        bands = [
            AgeBand(lower=lower, upper=upper, weighting=1) for lower, upper in parsed.age_bands
        ]
        lower = min(band.lower for band in bands)
        upper = max(band.upper for band in bands)
        return AudienceFilter(
            filter_id=target.filter_id,
            label=target.title,
            kind="range",
            lower=lower,
            upper=upper,
            age_bands=bands,
        )
    if parsed.age is None:
        return None
    return AudienceFilter(
        filter_id=target.filter_id,
        label=target.title,
        kind="range",
        lower=parsed.age[0],
        upper=parsed.age[1],
    )


def _sex_filter(mode: str, catalog: list[CatalogFilter]) -> AudienceFilter | None:
    """Build a sex filter.

    Args:
        mode: ``half``, ``female``, ``male``, or empty.
        catalog: Live filters.

    Returns:
        A select filter, or None.
    """
    if not mode:
        return None
    target = _find(catalog, ("sex", "gender"), "sex")
    if target is None:
        return None
    female = _choice(target, ("female", "woman"))
    male = _choice(target, ("male", "man"))
    selected: list[tuple[str, str]] = []
    if mode in {"half", "female"} and female:
        selected.append(female)
    if mode in {"half", "male"} and male:
        selected.append(male)
    if not selected:
        return None
    weights = {choice_id: 1.0 for choice_id, _label in selected} if mode == "half" else {}
    return AudienceFilter(
        filter_id=target.filter_id,
        label=target.title,
        kind="select",
        selected_values=[choice_id for choice_id, _label in selected],
        choice_labels={choice_id: label for choice_id, label in selected},
        weightings=weights,
    )


def _from_catalog(match: CatalogFilter, item: ProposedFilter) -> tuple[AudienceFilter | None, str]:
    """Convert one proposed filter after its id has been found.

    Args:
        match: Catalog row.
        item: Proposal.

    Returns:
        Filter and an empty problem, or None and a problem string.
    """
    if match.kind == "range":
        if item.lower is None and item.upper is None:
            return None, f"{match.title} needs a lower or upper bound."
        return (
            AudienceFilter(
                filter_id=match.filter_id,
                label=match.title,
                kind="range",
                lower=item.lower,
                upper=item.upper,
            ),
            "",
        )
    selected: list[str] = []
    labels: dict[str, str] = {}
    lookup = {label.lower(): (choice_id, label) for choice_id, label in match.choices.items()}
    for wanted in item.selected_labels:
        found = lookup.get(wanted.lower())
        if found is None:
            return None, f"{match.title} has no choice {wanted}."
        selected.append(found[0])
        labels[found[0]] = found[1]
    if not selected:
        return None, f"{match.title} needs at least one choice."
    weights = {
        choice_id: item.weights[label]
        for choice_id, label in labels.items()
        if label in item.weights
    }
    return (
        AudienceFilter(
            filter_id=match.filter_id,
            label=match.title,
            kind="select",
            selected_values=selected,
            choice_labels=labels,
            weightings=weights,
        ),
        "",
    )


def _find(
    catalog: list[CatalogFilter], ids: tuple[str, ...], title_word: str
) -> CatalogFilter | None:
    """Find a filter by id, then by a word in its title.

    Args:
        catalog: Live filters.
        ids: Preferred ids.
        title_word: Word that identifies the filter.

    Returns:
        Catalog row, or None.
    """
    for filter_id in ids:
        for item in catalog:
            if item.filter_id == filter_id:
                return item
    for item in catalog:
        if title_word in item.title.lower() or title_word in item.filter_id:
            return item
    return None


def _choice(target: CatalogFilter, words: tuple[str, ...]) -> tuple[str, str] | None:
    """Find a choice whose label contains one of the words.

    Args:
        target: Select filter.
        words: Label fragments.

    Returns:
        Choice id and label, or None.
    """
    for choice_id, label in target.choices.items():
        tokens = set(re.findall(r"[a-z]+", label.lower()))
        if any(word in tokens for word in words):
            return choice_id, label
    return None


def api_filters(filters: list[AudienceFilter], weighted: bool = True) -> list[dict]:
    """Serialize filters for eligibility and study creation.

    Args:
        filters: Audience filters.
        weighted: Whether to include quota weightings. The eligibility count leaves
            them out, because weights split places and do not change who qualifies.

    Returns:
        Prolific filter objects.
    """
    payload: list[dict] = []
    for item in filters:
        if item.kind == "range":
            selected: dict[str, int] = {}
            if item.lower is not None:
                selected["lower"] = item.lower
            if item.upper is not None:
                selected["upper"] = item.upper
            body: dict = {"filter_id": item.filter_id, "selected_range": selected}
            if weighted and item.age_bands:
                body["weightings"] = {
                    str(index): {
                        "selected_range": {"lower": band.lower, "upper": band.upper},
                        "weighting": band.weighting,
                    }
                    for index, band in enumerate(item.age_bands, start=1)
                }
            payload.append(body)
            continue
        body = {"filter_id": item.filter_id, "selected_values": item.selected_values}
        if weighted and item.weightings:
            body["weightings"] = item.weightings
        payload.append(body)
    return payload


def has_weightings(filters: list[AudienceFilter]) -> bool:
    """Return whether any filter splits places by weight.

    Args:
        filters: Audience filters.

    Returns:
        True when Prolific must create the study as a QUOTA study.
    """
    return any(item.weightings or item.age_bands for item in filters)
