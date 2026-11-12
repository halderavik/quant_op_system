"""Write synthetic respondents to SPSS and check the file before it is published."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import pyreadstat

from app.engines.offscale import off_scale_codes
from app.engines.spss import read_spss
from app.engines.synthetic_draw import code_value
from app.engines.synthetic_sim import Simulation
from app.engines.synthetic_survey import Spec
from app.schemas.common import ValidationCheck
from app.schemas.synthetic import QuotaCount

_PERSONA = "SYN_PERSONA"
_LABEL_LIMIT = 250


def build_frame(specs: list[Spec], simulation: Simulation) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Lay the respondents out as SPSS columns.

    Args:
        specs: Survey steps.
        simulation: Completed respondents.

    Returns:
        Data frame and the metadata pyreadstat needs: labels, value labels, and measures.
    """
    columns: list[str] = ["record"]
    labels: dict[str, str] = {"record": "Respondent record id"}
    values: dict[str, dict[Any, str]] = {}
    measures: dict[str, str] = {"record": "nominal"}
    text_columns: set[str] = set()
    for spec in specs:
        if not spec.answered:
            continue
        for index, name in enumerate(spec.names):
            columns.append(name)
            labels[name] = _label(spec, index)
            measures[name] = _measure(spec)
            coded = _value_labels(spec)
            if coded:
                values[name] = coded
            if spec.kind in {"text", "date"} or (coded is None and _string_codes(spec)):
                text_columns.add(name)
        for row in spec.rows:
            name = spec.open_names.get(row.label)
            if name:
                columns.append(name)
                labels[name] = _clip(f"{spec.label} {row.text}: specify")
                measures[name] = "nominal"
                text_columns.add(name)
    columns.append(_PERSONA)
    labels[_PERSONA] = "Synthetic persona (generator metadata, not a survey answer)"
    measures[_PERSONA] = "nominal"
    text_columns.add(_PERSONA)
    rows: list[dict[str, Any]] = []
    for number, person in enumerate(simulation.respondents, start=1):
        row: dict[str, Any] = {"record": number, _PERSONA: person.persona}
        row.update(person.values)
        rows.append(row)
    frame = pd.DataFrame(rows, columns=columns)
    for name in columns:
        if name in text_columns:
            frame[name] = frame[name].astype(object).where(frame[name].notna(), "")
        else:
            frame[name] = pd.to_numeric(frame[name], errors="coerce")
    missing = {
        name: codes[:3]
        for name, codes in (
            (name, off_scale_codes(value_labels)) for name, value_labels in values.items()
        )
        if codes
    }
    meta = {"labels": labels, "values": values, "measures": measures, "missing": missing}
    return frame, meta


def write_sav(frame: pd.DataFrame, meta: dict[str, Any]) -> bytes:
    """Write the frame to ``.sav`` bytes.

    Args:
        frame: Respondent rows.
        meta: Output of ``build_frame``.

    Returns:
        File bytes.
    """
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "synthetic.sav"
        pyreadstat.write_sav(
            frame,
            str(path),
            column_labels=[meta["labels"].get(name, name) for name in frame.columns],
            variable_value_labels=meta["values"],
            variable_measure=meta["measures"],
            missing_ranges=meta.get("missing") or None,
        )
        return path.read_bytes()


def check_file(
    payload: bytes,
    frame: pd.DataFrame,
    specs: list[Spec],
    simulation: Simulation,
    sample_size: int,
) -> tuple[list[ValidationCheck], list[QuotaCount]]:
    """Check the generated data against the survey rules and the sample target.

    Args:
        payload: The written ``.sav`` file.
        frame: Data that was written.
        specs: Survey steps.
        simulation: Respondents, with the questions each one saw.
        sample_size: Completes asked for.

    Returns:
        Checks and the achieved count for each quota cell.
    """
    people = simulation.respondents
    checks = [
        _check(
            "completes_match_target",
            len(people) == sample_size,
            f"{len(people)} completes for a target of {sample_size}.",
        )
    ]
    quotas: list[QuotaCount] = []
    by_label = {spec.label: spec for spec in specs if spec.answered}
    for target, wanted in simulation.quota_cells:
        spec = by_label[target.question]
        achieved = sum(
            _in_cell(person.values.get(spec.names[0]), spec, target) for person in people
        )
        quotas.append(
            QuotaCount(
                question=target.question, label=target.label, target=wanted, achieved=achieved
            )
        )
    missed = [item for item in quotas if item.achieved != item.target]
    checks.append(
        _check(
            "quota_cells_met",
            not missed,
            "Every quota cell has its target."
            if quotas and not missed
            else ("No quotas were set." if not quotas else _quota_detail(missed)),
        )
    )
    checks.append(_labeled(specs, people))
    checks.append(_ranks(specs, people))
    checks.append(_totals(specs, people))
    checks.append(_skips(specs, people))
    checks.append(_readback(payload, frame))
    return checks, quotas


def _check(check_id: str, ok: bool, details: str) -> ValidationCheck:
    """Build one deterministic check."""
    return ValidationCheck(id=check_id, status="passed" if ok else "failed", details=details)


def _quota_detail(missed: list[QuotaCount]) -> str:
    """Describe quota cells that missed their target."""
    return "; ".join(
        f"{item.question} {item.label}: {item.achieved} of {item.target}" for item in missed[:6]
    )


def _in_cell(value: Any, spec: Spec, target: Any) -> bool:
    """Return whether a stored value falls in a quota cell."""
    if value is None:
        return False
    if spec.kind == "single":
        return value == code_value(target.code or "")
    if spec.kind == "multi":
        return False
    lower = target.lower if target.lower is not None else float("-inf")
    upper = target.upper if target.upper is not None else float("inf")
    return lower <= float(value) <= upper


def _labeled(specs: list[Spec], people: list[Any]) -> ValidationCheck:
    """Every single-select and grid value is one of the question's codes."""
    bad: list[str] = []
    for spec in specs:
        if spec.kind not in {"single", "grid"}:
            continue
        choices = spec.rows if spec.kind == "single" else spec.cols
        allowed = {code_value(choice.code) for choice in choices}
        for name in spec.names:
            if any(
                person.values.get(name) is not None and person.values.get(name) not in allowed
                for person in people
            ):
                bad.append(name)
    return _check(
        "codes_are_labeled",
        not bad,
        "Every coded answer is a questionnaire code."
        if not bad
        else "Unlabeled codes in " + ", ".join(bad[:8]),
    )


def _ranks(specs: list[Spec], people: list[Any]) -> ValidationCheck:
    """Each respondent uses every rank position once."""
    bad: list[str] = []
    for spec in specs:
        if spec.kind != "rank":
            continue
        positions = min(spec.positions or len(spec.rows), len(spec.rows))
        for person in people:
            if spec.label not in person.asked:
                continue
            ranks = [person.values.get(name) for name in spec.names]
            used = sorted(rank for rank in ranks if rank is not None)
            if used != list(range(1, positions + 1)):
                bad.append(spec.label)
                break
    return _check(
        "ranks_are_unique",
        not bad,
        "Every rank question uses each position once."
        if not bad
        else "Repeated or missing ranks in " + ", ".join(bad),
    )


def _totals(specs: list[Spec], people: list[Any]) -> ValidationCheck:
    """Each allocation adds up to 100."""
    bad = [
        spec.label
        for spec in specs
        if spec.kind == "allocation"
        and any(
            sum(person.values.get(name) or 0 for name in spec.names) != 100
            for person in people
            if spec.label in person.asked
        )
    ]
    return _check(
        "allocations_total_100",
        not bad,
        "Every allocation totals 100." if not bad else "Totals other than 100 in " + ", ".join(bad),
    )


def _skips(specs: list[Spec], people: list[Any]) -> ValidationCheck:
    """A question the respondent was not shown stays blank."""
    bad: list[str] = []
    for spec in specs:
        if not spec.answered:
            continue
        for person in people:
            if spec.label in person.asked:
                continue
            if any(person.values.get(name) not in (None, "") for name in spec.names):
                bad.append(spec.label)
                break
    asked = sum(len(person.asked) for person in people)
    return _check(
        "skipped_questions_blank",
        not bad,
        f"Answers exist only where the survey showed the question ({asked} answered questions)."
        if not bad
        else "Answers on hidden questions: " + ", ".join(bad[:8]),
    )


def _readback(payload: bytes, frame: pd.DataFrame) -> ValidationCheck:
    """The written file reads back with the same rows and columns."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "check.sav"
        path.write_bytes(payload)
        try:
            data, variables, _ = read_spss(path)
        except Exception as exc:  # noqa: BLE001 - any read failure fails the check
            return _check(
                "spss_reads_back", False, f"The .sav file could not be read back ({exc})."
            )
    ok = len(data) == len(frame) and len(variables) == len(frame.columns)
    return _check(
        "spss_reads_back",
        ok,
        f"The .sav file reads back with {len(data)} rows and {len(variables)} variables.",
    )


def _label(spec: Spec, index: int) -> str:
    """Variable label for one stored value."""
    if spec.kind in {"single", "number", "text", "date"}:
        return _clip(f"{spec.label}: {spec.title}")
    row = spec.rows[index] if index < len(spec.rows) else None
    return _clip(f"{spec.label} {row.text if row else ''}: {spec.title}")


def _clip(text: str) -> str:
    """Keep a label inside SPSS's comfortable length."""
    clean = " ".join(text.split())
    return clean if len(clean) <= _LABEL_LIMIT else clean[: _LABEL_LIMIT - 1] + "…"


def _measure(spec: Spec) -> str:
    """SPSS measurement level."""
    if spec.kind == "rank":
        return "ordinal"
    if spec.kind in {"number", "allocation"}:
        return "scale"
    return "nominal"


def _string_codes(spec: Spec) -> bool:
    """Return whether any code is not a number, so the column must be text."""
    choices = spec.rows if spec.kind == "single" else spec.cols
    return any(isinstance(code_value(choice.code), str) for choice in choices)


def _value_labels(spec: Spec) -> dict[Any, str] | None:
    """Value labels for a coded question, or None when it has none or uses text codes."""
    if spec.kind == "multi":
        return {0: "Not selected", 1: "Selected"}
    if spec.kind == "rank":
        positions = min(spec.positions or len(spec.rows), len(spec.rows))
        return {rank: f"Rank {rank}" for rank in range(1, positions + 1)}
    if spec.kind not in {"single", "grid"}:
        return None
    if _string_codes(spec):
        return None
    choices = spec.rows if spec.kind == "single" else spec.cols
    return {code_value(choice.code): _clip(choice.text) for choice in choices}
