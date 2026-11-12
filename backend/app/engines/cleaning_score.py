"""Turn closed-end and open-end flags into a keep, review, or remove recommendation."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.engines.cleaning_oe import OpenScan, PendingVerbatim, scan_open_ends
from app.engines.cleaning_rules import ClosedScan, scan_closed
from app.schemas.cleaning import (
    CleaningReport,
    CleaningRule,
    CleaningSummary,
    OpenEndFinding,
    RespondentDisposition,
    RespondentFlag,
    VerbatimJudgement,
)
from app.schemas.common import ValidationCheck

_HARD = {"trap_fail", "oe_gibberish", "exact_duplicate", "duplicate_id"}
_OPEN_RULES: dict[str, tuple[str, str, str]] = {
    "oe_gibberish": (
        "Gibberish open end",
        "hard",
        "The open end is a keyboard walk, a repeated character, or letter mash.",
    ),
    "oe_nonsubstantive": (
        "Non-substantive open end",
        "soft",
        "The open end is a placeholder such as n/a, none, or idk."
        " One weak open end reviews the row only with a second weak open end or another flag.",
    ),
    "oe_duplicate": (
        "Duplicate open end",
        "soft",
        "The same long verbatim appears for more than one respondent.",
    ),
    "oe_repeated": (
        "Repeated open end",
        "soft",
        "The same respondent pasted one verbatim into more than one open end.",
    ),
    "oe_short": (
        "Short explanation",
        "soft",
        "A why or explain question has fewer than three words."
        " One weak open end reviews the row only with a second weak open end or another flag.",
    ),
    "oe_off_topic": (
        "Off-topic open end",
        "soft",
        "Semantic review marked the verbatim as not answering the question."
        " One weak open end reviews the row only with a second weak open end or another flag.",
    ),
    "oe_low_effort": (
        "Low-effort open end",
        "soft",
        "Semantic review marked the verbatim as a non-answer."
        " One weak open end reviews the row only with a second weak open end or another flag.",
    ),
    "oe_unreviewed": (
        "Open end not reviewed",
        "soft",
        "Semantic review did not classify this verbatim, so the respondent stays in review.",
    ),
}
_MODEL_RULES = {"off_topic": "oe_off_topic", "low_effort": "oe_low_effort"}
# Reason: one weak answer is common among real respondents. It reviews a row only
# when a second weak open end or another flag backs it up.
_WEAK = {"oe_nonsubstantive", "oe_short", "oe_off_topic", "oe_low_effort"}
_WEAK_LIMIT = 2


def recommend(
    frame: pd.DataFrame,
    variables: list[dict[str, Any]],
    *,
    dataset_id: str = "",
    source_sha256: str = "",
    judgements: list[VerbatimJudgement] | None = None,
    unreviewed_rows: set[int] | None = None,
    semantic_review: str = "Semantic review was not needed.",
) -> CleaningReport:
    """Build the recommendation from the data frame and any verbatim labels.

    Args:
        frame: Respondent rows.
        variables: SPSS dictionary.
        dataset_id: Active dataset id.
        source_sha256: Hash of the uploaded file. The file itself is not changed.
        judgements: Model labels for undecided verbatims.
        unreviewed_rows: Rows whose undecided text was not classified.
        semantic_review: Sentence stored on the summary.

    Returns:
        Recommendation. Keep, review, and remove add up to the row count.
    """
    closed = scan_closed(frame, variables)
    opened = scan_open_ends(frame, closed.text_columns)
    return assemble(
        closed,
        opened,
        judgements or [],
        unreviewed_rows or set(),
        dataset_id=dataset_id,
        source_sha256=source_sha256,
        semantic_review=semantic_review,
    )


def assemble(
    closed: ClosedScan,
    opened: OpenScan,
    judgements: list[VerbatimJudgement],
    unreviewed_rows: set[int],
    *,
    dataset_id: str,
    source_sha256: str,
    semantic_review: str,
) -> CleaningReport:
    """Merge flags into one disposition per respondent.

    Args:
        closed: Closed-end scan.
        opened: Open-end scan.
        judgements: Model labels.
        unreviewed_rows: Rows left in review because semantic review did not cover them.
        dataset_id: Active dataset id.
        source_sha256: Uploaded-file hash.
        semantic_review: Sentence stored on the summary.

    Returns:
        Recommendation.
    """
    flags = {index: list(items) for index, items in closed.flags.items()}
    for index, items in opened.flags.items():
        flags.setdefault(index, []).extend(items)
    findings = list(opened.findings)
    _apply_judgements(flags, findings, opened.pending, judgements)
    for index in unreviewed_rows:
        if index < 0 or index >= closed.row_count:
            continue
        flags.setdefault(index, []).append(
            ("oe_unreviewed", "Semantic review did not classify an open end on this row.")
        )
    respondents = [
        _respondent(index, closed.respondent_ids[index], flags.get(index, []))
        for index in range(closed.row_count)
    ]
    _stamp_ids(findings, closed.respondent_ids)
    summary = _summary(respondents, closed, opened, semantic_review)
    rules = _rules(closed, opened)
    return CleaningReport(
        dataset_id=dataset_id,
        source_sha256=source_sha256,
        rules=rules,
        respondents=respondents,
        open_ends=findings,
        summary=summary,
    )


def validate_cleaning(report: CleaningReport) -> list[ValidationCheck]:
    """Check that the dispositions add up and every flagged row names a rule.

    Args:
        report: Recommendation.

    Returns:
        Deterministic checks. A failed check is an error.
    """
    summary = report.summary
    total = summary.keep_n + summary.review_n + summary.remove_n
    counts_ok = total == summary.row_count == len(report.respondents)
    missing = [
        row.respondent_id
        for row in report.respondents
        if row.disposition != "keep" and not row.rule_ids
    ]
    return [
        ValidationCheck(
            id="disposition_total",
            status="passed" if counts_ok else "failed",
            details=f"{summary.keep_n} keep, {summary.review_n} review, {summary.remove_n} remove",
        ),
        ValidationCheck(
            id="flagged_have_rules",
            status="passed" if not missing else "failed",
            details=(
                "Every review or remove row has a rule."
                if not missing
                else "Missing rules for " + ", ".join(missing[:8])
            ),
        ),
    ]


def kept_positions(report: CleaningReport, row_count: int) -> list[int]:
    """Return the row positions that are not recommended for removal.

    Args:
        report: Recommendation.
        row_count: Length of the frame the recommendation was built from.

    Returns:
        Positions to keep. Review rows stay.
    """
    remove = {row.source_row_id for row in report.respondents if row.disposition == "remove"}
    return [index for index in range(row_count) if index not in remove]


def _apply_judgements(
    flags: dict[int, list[tuple[str, str]]],
    findings: list[OpenEndFinding],
    pending: list[PendingVerbatim],
    judgements: list[VerbatimJudgement],
) -> None:
    """Add a review flag when the model marks a verbatim off-topic or low-effort.

    Args:
        flags: Accumulator.
        findings: Exception rows.
        pending: Undecided verbatims, keyed by surrogate id.
        judgements: Model labels. Unknown ids are ignored.
    """
    by_id = {item.surrogate_id: item for item in pending}
    for judgement in judgements:
        item = by_id.get(judgement.surrogate_id)
        if item is None:
            continue
        rule_id = _MODEL_RULES.get(judgement.label)
        note = judgement.note.strip()
        # Reason: the variable keeps two weak answers with the same note from merging into one flag.
        detail = (
            f"{item.variable}: {note}"
            if note
            else f"Semantic review labeled {item.variable} {judgement.label}."
        )
        if rule_id:
            flags.setdefault(item.source_row_id, []).append((rule_id, detail))
        findings.append(
            OpenEndFinding(
                source_row_id=item.source_row_id,
                respondent_id=str(item.source_row_id),
                variable=item.variable,
                text_preview=item.text[:160],
                rule_id=rule_id or "oe_review",
                detail=detail,
                model_label=judgement.label,
            )
        )


def _respondent(
    index: int,
    respondent_id: str,
    items: list[tuple[str, str]],
) -> RespondentDisposition:
    """Choose keep, review, or remove for one row.

    Args:
        index: Row position.
        respondent_id: Display id.
        items: Rule id and detail pairs.

    Returns:
        Disposition. A hard fail, two straight-lined batteries, or speeding plus
        straight-lining removes the row. A single weak open end with no other flag
        keeps the row, and the flag stays on it for the reader.
    """
    unique: list[RespondentFlag] = []
    seen: set[tuple[str, str]] = set()
    for rule_id, detail in items:
        key = (rule_id, detail)
        if key in seen:
            continue
        seen.add(key)
        unique.append(RespondentFlag(rule_id=rule_id, detail=detail))
    rule_ids: list[str] = []
    for item in unique:
        if item.rule_id not in rule_ids:
            rule_ids.append(item.rule_id)
    straightline_count = sum(item.rule_id == "straightline" for item in unique)
    hard = _HARD.intersection(rule_ids)
    weak_n = sum(item.rule_id in _WEAK for item in unique)
    other = any(item.rule_id not in _WEAK for item in unique)
    if hard or straightline_count >= 2 or ("speeding" in rule_ids and straightline_count >= 1):
        disposition = "remove"
    elif other or weak_n >= _WEAK_LIMIT:
        disposition = "review"
    else:
        disposition = "keep"
    return RespondentDisposition(
        source_row_id=index,
        respondent_id=respondent_id,
        disposition=disposition,  # type: ignore[arg-type]
        rule_ids=rule_ids,
        flags=unique,
    )


def _stamp_ids(findings: list[OpenEndFinding], respondent_ids: list[str]) -> None:
    """Copy the display id onto each open-end finding.

    Args:
        findings: Exception rows.
        respondent_ids: Display ids in row order.
    """
    for finding in findings:
        if 0 <= finding.source_row_id < len(respondent_ids):
            finding.respondent_id = respondent_ids[finding.source_row_id]


def _summary(
    respondents: list[RespondentDisposition],
    closed: ClosedScan,
    opened: OpenScan,
    semantic_review: str,
) -> CleaningSummary:
    """Count dispositions and weighted shares.

    Args:
        respondents: One row per respondent.
        closed: Closed-end scan, including weights and skip sentences.
        opened: Open-end scan.
        semantic_review: Sentence stored on the summary.

    Returns:
        Summary. Shares are omitted when the file has no positive weight.
    """
    keep_n = sum(row.disposition == "keep" for row in respondents)
    review_n = sum(row.disposition == "review" for row in respondents)
    remove_n = sum(row.disposition == "remove" for row in respondents)
    counts: dict[str, int] = {}
    for row in respondents:
        for rule_id in row.rule_ids:
            counts[rule_id] = counts.get(rule_id, 0) + 1
    skipped = list(closed.skipped)
    if opened.skip_reason:
        skipped.append(opened.skip_reason)
    remove_share, review_share = _shares(respondents, closed.weights)
    return CleaningSummary(
        row_count=len(respondents),
        keep_n=keep_n,
        review_n=review_n,
        remove_n=remove_n,
        weighted_remove_share=remove_share,
        weighted_review_share=review_share,
        weight_variable=closed.weight_name,
        skipped=skipped,
        rule_counts=counts,
        semantic_review=semantic_review,
    )


def _shares(
    respondents: list[RespondentDisposition],
    weights: list[float] | None,
) -> tuple[float | None, float | None]:
    """Return the weighted share of remove and review.

    Args:
        respondents: Dispositions.
        weights: Weight per row, or None.

    Returns:
        Two shares, or a pair of Nones when there is nothing to weight.
    """
    if not weights or len(weights) != len(respondents):
        return None, None
    total = sum(weights)
    if total <= 0:
        return None, None
    remove = sum(
        weight
        for weight, row in zip(weights, respondents, strict=True)
        if row.disposition == "remove"
    )
    review = sum(
        weight
        for weight, row in zip(weights, respondents, strict=True)
        if row.disposition == "review"
    )
    return remove / total, review / total


def _rules(closed: ClosedScan, opened: OpenScan) -> list[CleaningRule]:
    """List every rule, including open-end rules the closed-end pass does not own.

    Args:
        closed: Closed-end scan.
        opened: Open-end scan.

    Returns:
        Rule catalog with ran and skip reason filled in.
    """
    rules = list(closed.rules)
    reason = opened.skip_reason
    for rule_id, (label, severity, definition) in _OPEN_RULES.items():
        rules.append(
            CleaningRule(
                id=rule_id,
                label=label,
                definition=definition,
                severity=severity,  # type: ignore[arg-type]
                ran=not reason,
                skip_reason=reason,
            )
        )
    return rules
