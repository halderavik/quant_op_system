"""Respondent-level code frequencies. Nets are unions, not sums of percentages."""

from collections import Counter

from app.errors import AppError
from app.schemas.coding import Codeframe, CodeFrequency, CodingAssignment, CodingReport, Sentiment


def merge_checkpoint(
    existing: list[CodingAssignment],
    incoming: list[CodingAssignment],
) -> list[CodingAssignment]:
    """Append new rows and skip source ids that were already checkpointed.

    Args:
        existing: Rows already saved.
        incoming: A retried or continued batch.

    Returns:
        Combined rows with one entry per source row id.
    """
    seen = {row.source_row_id for row in existing}
    merged = list(existing)
    for row in incoming:
        if row.source_row_id in seen:
            continue
        merged.append(row)
        seen.add(row.source_row_id)
    return merged


def final_codes(assignment: CodingAssignment) -> list[str]:
    """Return reviewer codes when present, otherwise the model codes.

    Args:
        assignment: Row assignment.

    Returns:
        Code ids without duplicates, preserving order.
    """
    source = (
        assignment.human_overrides.code_ids
        if assignment.human_overrides is not None
        else assignment.assigned_code_ids
    )
    seen: list[str] = []
    for code in source:
        if code not in seen:
            seen.append(code)
    return seen


def final_sentiment(assignment: CodingAssignment) -> Sentiment | None:
    """Return the reviewer sentiment when set.

    Args:
        assignment: Row assignment.

    Returns:
        Sentiment label or None.
    """
    if assignment.human_overrides and assignment.human_overrides.sentiment:
        return assignment.human_overrides.sentiment
    return assignment.sentiment


def aggregate(
    codeframe: Codeframe,
    assignments: list[CodingAssignment],
    weights: dict[str, float] | None = None,
) -> CodingReport:
    """Compute code, net, and sentiment frequencies.

    Args:
        codeframe: Approved codeframe.
        assignments: Row assignments. One row per response key.
        weights: Optional weight by respondent id. Missing weights count as missing,
            not as 1.

    Returns:
        Frequency report.

    Raises:
        AppError: When a code id is not in the frame or a row key repeats.
    """
    known = {code.id for code in codeframe.codes}
    seen_rows: set[int] = set()
    substantive: list[CodingAssignment] = []
    nonsubstantive = 0
    for row in assignments:
        if row.source_row_id in seen_rows:
            raise AppError(f"Duplicate response row {row.source_row_id}", "duplicate_row")
        seen_rows.add(row.source_row_id)
        if not row.substantive or _placeholder(row.response_text, codeframe.placeholders):
            nonsubstantive += 1
            continue
        unknown = [code for code in final_codes(row) if code not in known]
        if unknown:
            raise AppError(
                f"Assignment uses code ids that are not in the codeframe: {', '.join(unknown)}",
                "invalid_code",
            )
        if not codeframe.allow_multiple_codes and len(final_codes(row)) > 1:
            raise AppError("This codeframe allows one code per response.", "invalid_code")
        substantive.append(row)
    base_u = len(substantive)
    base_w = 0.0
    for row in substantive:
        base_w += _weight(row.respondent_id, weights)
    frequencies: list[CodeFrequency] = []
    for code in codeframe.codes:
        members = [row for row in substantive if code.id in final_codes(row)]
        frequencies.append(
            _freq(code.id, code.label, "code", members, base_u, base_w, weights, mentions=True)
        )
    for net in codeframe.nets:
        if net.id in set(net.child_ids):
            raise AppError(f"Net {net.id} includes itself.", "bad_codeframe")
        unknown = [
            child
            for child in net.child_ids
            if child not in known and child not in {item.id for item in codeframe.nets}
        ]
        # Child codes must exist. Nested nets are not expanded in this version.
        missing_codes = [child for child in net.child_ids if child not in known]
        if missing_codes:
            raise AppError(
                f"Net {net.id} references unknown codes: {', '.join(missing_codes)}",
                "bad_codeframe",
            )
        members = [
            row for row in substantive if any(child in final_codes(row) for child in net.child_ids)
        ]
        frequencies.append(
            _freq(net.id, net.label, "net", members, base_u, base_w, weights, mentions=False)
        )
    frequencies.append(
        CodeFrequency(
            id="NO_ANSWER",
            label="No answer",
            kind="bucket",
            unweighted_respondents=nonsubstantive,
            weighted_respondents=float(nonsubstantive),
            base_unweighted=len(assignments),
            base_weighted=float(len(assignments)),
            pct_of_respondents=(100.0 * nonsubstantive / len(assignments)) if assignments else None,
        )
    )
    sentiment = Counter(
        final_sentiment(row) for row in substantive if final_sentiment(row) is not None
    )
    return CodingReport(
        frequencies=frequencies,
        sentiment_counts={str(key): int(value) for key, value in sentiment.items()},
        substantive_n=base_u,
        nonsubstantive_n=nonsubstantive,
        warnings=[
            "Net percentages are respondent unions. Multi-label code percentages do not add to 100."
        ],
    )


def sanitize_codes(code_ids: list[str], codeframe: Codeframe) -> tuple[list[str], list[str]]:
    """Drop code ids that are not in the current codeframe.

    Args:
        code_ids: Ids returned by a model.
        codeframe: Approved frame.

    Returns:
        Kept ids and rejected ids.
    """
    known = {code.id for code in codeframe.codes}
    kept: list[str] = []
    rejected: list[str] = []
    for code in code_ids:
        if code in known and code not in kept:
            kept.append(code)
        elif code not in known:
            rejected.append(code)
    return kept, rejected


def _freq(
    code_id: str,
    label: str,
    kind: str,
    members: list[CodingAssignment],
    base_u: int,
    base_w: float,
    weights: dict[str, float] | None,
    *,
    mentions: bool,
) -> CodeFrequency:
    """Build one frequency row.

    Args:
        code_id: Code or net id.
        label: Display label.
        kind: ``code``, ``net``, or ``bucket``.
        members: Distinct respondents in the numerator.
        base_u: Unweighted substantive base.
        base_w: Weighted substantive base.
        weights: Weight map.
        mentions: Include a mention count equal to the respondent count for single codes.

    Returns:
        Frequency row.
    """
    unw = len(members)
    weighted = sum(_weight(row.respondent_id, weights) for row in members)
    pct = (
        None
        if base_w == 0 and base_u == 0
        else (
            100.0 * (weighted if weights else unw) / (base_w if weights else base_u)
            if (base_w if weights else base_u)
            else None
        )
    )
    return CodeFrequency(
        id=code_id,
        label=label,
        kind=kind,  # type: ignore[arg-type]
        unweighted_respondents=unw,
        weighted_respondents=weighted,
        base_unweighted=base_u,
        base_weighted=base_w,
        pct_of_respondents=pct,
        unweighted_mentions=unw if mentions else None,
        weighted_mentions=weighted if mentions else None,
    )


def _weight(respondent_id: str, weights: dict[str, float] | None) -> float:
    """Return a respondent weight.

    Args:
        respondent_id: Respondent id.
        weights: Optional map.

    Returns:
        Weight, or 1 when no weight map was supplied.
    """
    if weights is None:
        return 1.0
    value = float(weights.get(respondent_id, 0.0))
    if value < 0:
        raise AppError("Negative weights are rejected.", "negative_weight")
    return value


def _placeholder(text: str, placeholders: list[str]) -> bool:
    """Return whether a response is blank or a listed non-substantive token.

    Args:
        text: Response text.
        placeholders: Tokens such as ``n/a``.

    Returns:
        True when the response should leave the sentiment base.
    """
    return text.strip().lower() in {item.strip().lower() for item in placeholders}
