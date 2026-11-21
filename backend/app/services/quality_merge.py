"""Add Live quality results to survey data as ``LQ_*`` variables.

A Decipher export of a tracked survey carries ``QOS_SESSION`` (and ``QOS_RESPONDENT``),
written by the tracker on the final page. This joins each record to its row in the
Live quality results, under the project's quality rules, so flags can be used in
tables, filters and cleaning like any other variable.
"""

from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.config import Settings
from app.errors import AppError
from app.repositories.records import DatasetRepository, ProjectRepository
from app.services import live_quality
from app.services.quality_rules import BOT_SIGNALS, get_rules
from app.services.storage import Storage
from app.util import new_id

PREFIX = "LQ_"
SESSION_COLUMN = "QOS_SESSION"
RESPONDENT_COLUMN = "QOS_RESPONDENT"

# One 0/1 variable per dashboard flag, in the dashboard's order.
FLAG_COLUMNS: tuple[tuple[str, str], ...] = (
    ("LQ_F_BOT", "Bot-like behaviour"),
    ("LQ_F_TEXT", "Low-quality open ends"),
    ("LQ_F_PASTED", "Pasted answers"),
    ("LQ_F_STRAIGHT", "Straight-lining"),
    ("LQ_F_SPEEDER", "Speeder"),
    ("LQ_F_FLATLINE", "Flatliner"),
    ("LQ_F_DUPLICATE", "Duplicate"),
    ("LQ_F_FRAUD", "High fraud risk"),
    ("LQ_F_DATACENTRE", "Data-centre IP"),
)
_BANDS = {"1": "Low (under 0.5)", "2": "Medium (0.5 to 0.7)", "3": "High (0.7 and over)"}
_YES_NO = {"0": "No", "1": "Yes"}


def _variable(
    name: str, label: str, *, values: dict[str, str] | None = None, text: bool = False, scale: bool = False
) -> dict[str, Any]:
    """A dataset variable entry in the same shape ``read_spss`` produces."""
    return {
        "name": name,
        "label": label,
        "kind": "text" if text else "numeric",
        "measurement": "nominal" if text or not scale else "scale",
        "value_labels": values or {},
        "user_missing_values": [],
        "is_text": text,
    }


def quality_variables() -> list[dict[str, Any]]:
    """Every ``LQ_*`` variable, with labels and value labels."""
    entries = [
        _variable("LQ_MATCHED", "[Live quality] Record found in Live quality results", values=_YES_NO),
        _variable(
            "LQ_STATUS", "[Live quality] Session status",
            values={"1": "Checked", "2": "In progress", "3": "Dropped or ended early"},
        ),
        _variable("LQ_VERDICT", "[Live quality] Verdict under the project's rules", values={"1": "Human", "2": "Bot", "3": "Not checked yet"}),
        _variable("LQ_BOT_SCORE", "[Live quality] Behaviour bot score (0 human to 1 bot)", scale=True),
        _variable("LQ_BOT_RISK", "[Live quality] Behaviour risk band", values=_BANDS),
        _variable("LQ_BOT_SIGNALS", "[Live quality] Decisive bot signals that fired", text=True),
        _variable("LQ_SECONDS", "[Live quality] Seconds on tracked pages", scale=True),
        _variable("LQ_PAGES", "[Live quality] Tracked pages", scale=True),
        _variable("LQ_SEC_PER_PAGE", "[Live quality] Seconds per page", scale=True),
        _variable("LQ_TEXT_QUALITY", "[Live quality] Average open-end quality (0 poor to 1 good)", scale=True),
        _variable("LQ_FRAUD_SCORE", "[Live quality] Fraud score (0 genuine to 1 fraud)", scale=True),
        _variable("LQ_FRAUD_RISK", "[Live quality] Fraud risk band", values=_BANDS),
    ]
    entries += [_variable(name, f"[Live quality] Flag: {flag}", values=_YES_NO) for name, flag in FLAG_COLUMNS]
    entries += [
        _variable("LQ_NFLAGS", "[Live quality] Number of flags", scale=True),
        _variable("LQ_FLAGS", "[Live quality] All flags", text=True),
    ]
    return entries


def session_column(frame: pd.DataFrame) -> str | None:
    """The tracker's session column when the data has one with any values, else None."""
    for name in (SESSION_COLUMN, RESPONDENT_COLUMN):
        if name in frame.columns and frame[name].astype(str).str.strip().replace("nan", "").ne("").any():
            return name
    return None


def _band(score: Any) -> float:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return np.nan
    return 3.0 if value >= 0.7 else 2.0 if value >= 0.5 else 1.0


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def _key(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text.lower() == "nan" else text


def _values(row: dict[str, Any] | None) -> dict[str, Any]:
    """The ``LQ_*`` values for one dashboard row, or the unmatched defaults."""
    if row is None:
        blank: dict[str, Any] = {entry["name"]: ("" if entry["is_text"] else np.nan) for entry in quality_variables()}
        blank["LQ_MATCHED"] = 0.0
        return blank
    flags = list(row.get("flags") or [])
    seconds, pages = _number(row.get("seconds")), _number(row.get("pages")) or np.nan
    verdict = {"human": 1.0, "bot": 2.0}.get(str(row.get("verdict")), 3.0)
    status = {"checked": 1.0, "in_progress": 2.0}.get(str(row.get("status")), 3.0)
    fraud = _number(row.get("fraud_score"))
    fraud_band = _band(fraud)
    if np.isnan(fraud_band):
        fraud_band = {"LOW": 1.0, "MEDIUM": 2.0, "HIGH": 3.0, "CRITICAL": 3.0}.get(
            str(row.get("fraud_risk") or "").upper(), np.nan
        )
    values: dict[str, Any] = {
        "LQ_MATCHED": 1.0,
        "LQ_STATUS": status,
        "LQ_VERDICT": verdict,
        "LQ_BOT_SCORE": _number(row.get("confidence")),
        "LQ_BOT_RISK": {"low": 1.0, "medium": 2.0, "high": 3.0, "critical": 3.0}.get(str(row.get("risk")), np.nan),
        "LQ_BOT_SIGNALS": "; ".join(BOT_SIGNALS.get(code, code) for code in row.get("bot_signals") or []),
        "LQ_SECONDS": seconds,
        "LQ_PAGES": pages,
        "LQ_SEC_PER_PAGE": round(seconds / pages, 1) if pages and not np.isnan(seconds) else np.nan,
        "LQ_TEXT_QUALITY": _number(row.get("text_quality")),
        "LQ_FRAUD_SCORE": fraud,
        "LQ_FRAUD_RISK": fraud_band,
        "LQ_NFLAGS": float(len(flags)),
        "LQ_FLAGS": "; ".join(flags),
    }
    for name, flag in FLAG_COLUMNS:
        values[name] = 1.0 if flag in flags else 0.0
    return values


def add_quality_columns(
    frame: pd.DataFrame, variables: list[dict[str, Any]], result: dict[str, Any]
) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
    """Join Live quality rows to survey records and add the ``LQ_*`` variables.

    Records match on ``QOS_SESSION``, then on ``QOS_RESPONDENT``. Existing ``LQ_*``
    columns are replaced, so running it again refreshes the flags.

    Args:
        frame: Survey data.
        variables: Dataset variable entries.
        result: Payload from :func:`live_quality.live_results`.

    Returns:
        The new frame, the new variable list, and counts of what matched.
    """
    by_session: dict[str, dict[str, Any]] = {}
    by_respondent: dict[str, dict[str, Any]] = {}
    for row in result.get("respondents") or []:
        if _key(row.get("session_id")):
            by_session[_key(row.get("session_id"))] = row
        if _key(row.get("respondent_id")):
            by_respondent[_key(row.get("respondent_id"))] = row
    sessions = frame[SESSION_COLUMN] if SESSION_COLUMN in frame.columns else pd.Series([""] * len(frame), index=frame.index)
    respondents = frame[RESPONDENT_COLUMN] if RESPONDENT_COLUMN in frame.columns else pd.Series([""] * len(frame), index=frame.index)
    records = []
    tracked = 0
    for session, respondent in zip(sessions, respondents):
        session, respondent = _key(session), _key(respondent)
        tracked += bool(session or respondent)
        records.append(_values(by_session.get(session) or by_respondent.get(respondent)))
    added = pd.DataFrame(records, index=frame.index)
    kept = frame[[name for name in frame.columns if not str(name).startswith(PREFIX)]]
    merged = pd.concat([kept, added], axis=1)
    entries = quality_variables()
    for entry in entries:
        if entry["is_text"]:
            merged[entry["name"]] = merged[entry["name"]].fillna("").astype(str)
    new_variables = [item for item in variables if not str(item["name"]).startswith(PREFIX)] + entries
    matched = int(added["LQ_MATCHED"].sum())
    report = {
        "survey_id": result.get("survey_id"),
        "records": int(len(frame)),
        "tracked": tracked,
        "matched": matched,
        "unmatched": tracked - matched,
        "flagged": int((added["LQ_NFLAGS"].fillna(0) > 0).sum()),
        "bots": int((added["LQ_VERDICT"] == 2).sum()),
        "variables": [entry["name"] for entry in entries],
    }
    return merged, new_variables, report


def _remember(db: Session, project_id: str, report: dict[str, Any]) -> None:
    project = ProjectRepository(db).get(project_id)
    context = dict(project.study_context or {})
    current = dict(context.get("live_quality") or {})
    current["merged"] = report
    context["live_quality"] = current
    project.study_context = context
    flag_modified(project, "study_context")


def merge_state(db: Session, storage: Storage, project_id: str) -> dict[str, Any]:
    """Whether the active dataset can take Live quality results, and the last merge.

    Args:
        db: Session.
        storage: Project storage.
        project_id: Project id.

    Returns:
        ``tracked`` (the data has QOS session ids), ``merged`` (the active dataset already
        has LQ variables), and ``last`` (the last merge report, if any).
    """
    project = ProjectRepository(db).get(project_id)
    last = ((project.study_context or {}).get("live_quality") or {}).get("merged")
    if not project.active_dataset_id:
        return {"tracked": False, "merged": False, "last": last}
    dataset = DatasetRepository(db).get(project.active_dataset_id)
    names = {item["name"] for item in dataset.variables or []}
    return {
        "tracked": SESSION_COLUMN in names or RESPONDENT_COLUMN in names,
        "merged": "LQ_MATCHED" in names,
        "last": last,
    }


async def merge_into_dataset(
    db: Session,
    storage: Storage,
    settings: Settings,
    project_id: str,
    dataset: Any,
    *,
    new_version: bool,
) -> dict[str, Any]:
    """Fetch Live quality results and add them to a dataset.

    Never raises for a missing or unreachable service: the upload still succeeds and
    the report says why no flags were added.

    Args:
        db: Session.
        storage: Project storage.
        settings: Settings (bot-detection API base).
        project_id: Project id.
        dataset: Dataset row to read.
        new_version: Save as a new active dataset version (a refresh) instead of
            rewriting this dataset in place (a fresh upload).

    Returns:
        A report with ``status`` ``merged``, ``no_tracking``, ``no_results`` or ``unavailable``,
        and a ``message`` to show.
    """
    from app.services.execute import load_frame

    frame = load_frame(storage, dataset)
    if session_column(frame) is None:
        return {"status": "no_tracking", "message": "The data has no QOS_SESSION ids, so there is nothing to match."}
    survey_id = live_quality.tracking_settings(db, project_id)["survey_id"]
    try:
        result = await live_quality.live_results(settings, survey_id, get_rules(db, project_id))
    except AppError as exc:
        return {
            "status": "unavailable",
            "message": f"Live quality flags were not added: {exc.message} Try again from the Live quality tab.",
        }
    if not result.get("respondents"):
        return {
            "status": "no_results",
            "message": f"Live quality has no results for '{survey_id}', so no flags were added.",
        }
    merged, variables, report = add_quality_columns(frame, list(dataset.variables or []), result)
    target = dataset
    if new_version:
        dataset_id = new_id()
        relative = f"datasets/{dataset_id}.parquet"
        snapshot = storage.resolve(project_id, relative)
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        merged.to_parquet(snapshot)
        target = DatasetRepository(db).add(
            id=dataset_id,
            project_id=project_id,
            source_file_id=dataset.source_file_id,
            source_sha256=dataset.source_sha256,
            format=dataset.format,
            row_count=int(len(merged)),
            variables=variables,
            weight_candidates=list(dataset.weight_candidates or []),
            version=int(dataset.version) + 1,
            parquet_relpath=relative,
        )
        ProjectRepository(db).get(project_id).active_dataset_id = target.id
    else:
        merged.to_parquet(storage.resolve(project_id, dataset.parquet_relpath))
        dataset.variables = variables
        flag_modified(dataset, "variables")
    report.update(
        status="merged",
        dataset_id=target.id,
        merged_at=datetime.now(timezone.utc).isoformat(),
        message=(
            f"Added Live quality flags for {report['matched']} of {report['tracked']} tracked records "
            f"({report['flagged']} flagged, {report['bots']} bots) as LQ_ variables."
            + (
                f" {report['unmatched']} tracked records were not found in Live quality."
                if report["unmatched"]
                else ""
            )
        ),
    )
    _remember(db, project_id, report)
    db.flush()
    return report
