"""Deterministic work used by the orchestrator and the HTTP API."""

import re
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.config import Settings
from app.engines.analysis.registry import run_plan, validate_roles
from app.engines.analysis.report import analysis_summary, build_report
from app.engines.crosstab import run_table, run_tabspec
from app.engines.invariants import summarize, validate_export, validate_report, validate_table
from app.engines.spss import read_spss
from app.engines.tabbook_excel import export_tabbook
from app.engines.tabspec_excel import export_tabspec
from app.errors import AppError
from app.repositories.records import (
    ArtifactRepository,
    DatasetRepository,
    FileRepository,
    ProjectRepository,
)
from app.schemas.analysis import AnalysisPlan, AnalysisReport, VariableRole
from app.schemas.crosstab import TabBook, TableResult
from app.schemas.questionnaire import Questionnaire
from app.schemas.tabspec import (
    Banner,
    BannerCategory,
    SignificanceSpec,
    StudyDefaults,
    TableSpec,
    TabSpec,
)
from app.services.storage import Storage
from app.services.stored_files import _write_export
from app.util import new_id

_CODENAME = re.compile(r"codename is ([A-Za-z0-9_-]+)", re.I)
_CHANGE_TEXT = re.compile(r"change\s+([A-Za-z0-9_]+)\s+text\s+to\s+(.+)$", re.I)
_CHANGE_OPTION = re.compile(
    r"change\s+([A-Za-z0-9_]+)\s+option\s+([A-Za-z0-9_]+)\s+label\s+to\s+(.+)$",
    re.I,
)


def ingest_spss(
    db: Session, storage: Storage, settings: Settings, project_id: str, file_id: str
) -> Any:
    """Load an uploaded SPSS file into a parquet snapshot and dictionary.

    Args:
        db: Session.
        storage: Storage service.
        settings: Settings, including the upload limit.
        project_id: Project id.
        file_id: Stored file id.

    Returns:
        Dataset row.
    """
    stored = FileRepository(db).get(file_id)
    if stored.project_id != project_id:
        raise AppError("That file belongs to another project.", "not_found", 404)
    limit = settings.max_upload_mb * 1024 * 1024
    if stored.size_bytes > limit:
        raise AppError(
            "This file is larger than the configured limit. Raise MAX_UPLOAD_MB or upload a smaller extract.",
            "file_too_large",
        )
    path = storage.resolve(project_id, stored.storage_relpath)
    frame, variables, weights = read_spss(path)
    dataset_id = new_id()
    relative = f"datasets/{dataset_id}.parquet"
    snapshot = storage.resolve(project_id, relative)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(snapshot)
    dataset = DatasetRepository(db).add(
        id=dataset_id,
        project_id=project_id,
        source_file_id=stored.id,
        source_sha256=stored.sha256,
        format=path.suffix.lower().lstrip("."),
        row_count=int(len(frame)),
        variables=variables,
        weight_candidates=weights,
        version=1,
        parquet_relpath=relative,
    )
    project = ProjectRepository(db).get(project_id)
    if project.active_dataset_id is None:
        project.active_dataset_id = dataset.id
    return dataset


def load_frame(storage: Storage, dataset: Any) -> pd.DataFrame:
    """Load the columnar snapshot for a dataset.

    Args:
        storage: Storage service.
        dataset: Dataset row.

    Returns:
        Data frame.
    """
    return pd.read_parquet(storage.resolve(dataset.project_id, dataset.parquet_relpath))


def run_requested_crosstab(
    db: Session,
    storage: Storage,
    project_id: str,
    fields: dict[str, Any],
    *,
    enable_significance: bool,
) -> dict[str, Any]:
    """Run one table from named variables and store the result plus workbook.

    Args:
        db: Session.
        storage: Storage service.
        project_id: Project id.
        fields: Row, banner, and optional weight.
        enable_significance: Whether the user asked for a test.

    Returns:
        Summary payload with artifact ids.
    """
    dataset = _active_dataset(db, project_id)
    frame = load_frame(storage, dataset)
    spec = _single_spec(fields, dataset.variables, enable_significance)
    result = run_table(
        frame,
        dataset.variables,
        spec.tables[0],
        spec.study_defaults,
        spec.banners,
        dataset_id=dataset.id,
    )
    checks = validate_table(result, spec.tables[0].table_type)
    book = TabBook(tables=[result])
    file_id = _write_export(
        db,
        storage,
        project_id,
        f"{result.table_id}.xlsx",
        export_tabbook(book),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    export_path = storage.resolve(project_id, FileRepository(db).get(file_id).storage_relpath)
    checks.append(validate_export(export_path))
    report = summarize(checks)
    revision = ArtifactRepository(db).create(
        project_id=project_id,
        artifact_type="crosstab",
        name=result.title,
        content={
            "table": result.model_dump(mode="json"),
            "tables": [result.model_dump(mode="json")],
            "exceptions": [],
            "export_file_id": file_id,
            "spec": spec.model_dump(mode="json"),
        },
        content_schema="crosstab/1",
        created_by="crosstab",
        validation_status=report.status,
    )
    return {
        "summary": _crosstab_summary(result, fields),
        "status": "completed" if report.status == "passed" else "completed_with_warnings",
        "artifact_id": revision.artifact_id,
        "version": revision.version,
        "warnings": result.warnings,
        "validation": report.model_dump(mode="json"),
    }


def run_requested_analysis(
    db: Session, storage: Storage, project_id: str, fields: dict[str, Any]
) -> dict[str, Any]:
    """Run a registered method or refuse MaxDiff, conjoint, and missing roles.

    Args:
        db: Session.
        storage: Storage service.
        project_id: Project id.
        fields: Method and roles.

    Returns:
        Summary payload.
    """
    dataset = _active_dataset(db, project_id)
    plan = AnalysisPlan(
        analysis_id=new_id(),
        method=str(fields.get("method") or ""),
        dataset_id=dataset.id,
        dependent=(
            VariableRole(name=fields["dependent"], role="dependent")
            if fields.get("dependent")
            else None
        ),
        predictors=list(fields.get("predictors") or []),
        variables=list(fields.get("variables") or []),
        group=fields.get("group"),
        var_a=fields.get("var_a"),
        var_b=fields.get("var_b"),
        weight_variable=fields.get("weight_variable"),
        random_seed=int(fields.get("seed") or 42),
        options=dict(fields.get("options") or {}),
    )
    missing = validate_roles(plan)
    if missing:
        names = ", ".join(f"`{item['name']}`" for item in dataset.variables[:12])
        raise AppError(
            "I can run this after you select the missing roles from the uploaded dataset: "
            f"{', '.join(missing)}. The available fields include {names}.",
            "missing_roles",
        )
    frame = load_frame(storage, dataset)
    computed = run_plan(frame, plan)
    report = build_report(plan.method.replace("_", " "), computed)
    checks = validate_report(report, computed.model_dump(mode="json"))
    gate = summarize(checks)
    revision = ArtifactRepository(db).create(
        project_id=project_id,
        artifact_type="analysis",
        name=report.title,
        content={
            "plan": plan.model_dump(mode="json"),
            "result": computed.model_dump(mode="json"),
            "report": report.model_dump(mode="json"),
        },
        content_schema="analysis/1",
        created_by="analysis",
        validation_status=gate.status,
    )
    status = (
        "completed_with_warnings" if computed.warnings or gate.status != "passed" else "completed"
    )
    return {
        "summary": analysis_summary(plan.method, computed),
        "status": status,
        "artifact_id": revision.artifact_id,
        "version": revision.version,
        "warnings": computed.warnings,
        "validation": gate.model_dump(mode="json"),
    }


async def build_project_tabspec(
    db: Session,
    storage: Storage,
    settings: Settings,
    project_id: str,
    weight: str | None,
    *,
    session_id: str,
    on_stage: Any,
) -> dict[str, Any]:
    """Ask the validator for a spec and save it only after every table has a base.

    Args:
        db: Session.
        storage: Storage service.
        settings: Application settings. The validator model writes the plan.
        project_id: Project id.
        weight: Optional confirmed weight variable.
        session_id: SDK session id for the validator call.
        on_stage: Records a chat stage. Called with one message string.

    Returns:
        Summary payload.

    Raises:
        AppError: No dataset is active, the snapshot cannot be read, or the spec still
            produces an empty table.
    """
    from app.services.tabspec_guard import author_executable_tabspec

    artifacts = ArtifactRepository(db)
    questionnaire_row = artifacts.latest_of_type(project_id, "questionnaire")
    questionnaire = (
        Questionnaire.model_validate(questionnaire_row.content) if questionnaire_row else None
    )
    dataset = _active_dataset(db, project_id)
    try:
        frame = load_frame(storage, dataset)
    except (OSError, ValueError) as exc:
        raise AppError(
            "The dataset snapshot could not be read, so I cannot check that the tables have a base.",
            "missing_dataset",
        ) from exc
    questionnaire_ref = (
        {"artifact_id": questionnaire_row.artifact_id, "version": questionnaire_row.version}
        if questionnaire_row
        else None
    )
    spec, report, repairs = await author_executable_tabspec(
        settings,
        frame=frame,
        variables=dataset.variables,
        questionnaire=questionnaire,
        dataset_id=dataset.id,
        questionnaire_ref=questionnaire_ref,
        weight_variable=weight,
        session_id=session_id,
        on_stage=on_stage,
    )
    data = export_tabspec(spec)
    file_id = _write_export(
        db,
        storage,
        project_id,
        "tabspec.xlsx",
        data,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    derived = []
    if questionnaire_row:
        derived.append(
            {
                "type": "questionnaire",
                "id": questionnaire_row.artifact_id,
                "version": questionnaire_row.version,
            }
        )
    revision = artifacts.create(
        project_id=project_id,
        artifact_type="tabspec",
        name="Tab specification",
        content={**spec.model_dump(mode="json"), "export_file_id": file_id},
        content_schema="tabspec/1",
        created_by="tabspec",
        derived_from=derived,
        validation_status=report.status,
    )
    excluded = len(spec.exclusions)
    summary = (
        f"Built {len(spec.tables)} tables the dataset can tabulate. "
        f"{excluded} items were left off the crosstabs."
    )
    if repairs > 1:
        summary += " The validator corrected the spec so each table has a base."
    return {
        "summary": summary,
        "status": "completed_with_warnings" if spec.exclusions else "completed",
        "artifact_id": revision.artifact_id,
        "version": revision.version,
        "warnings": [item["reason"] for item in spec.exclusions[:5]],
        "validation": report.model_dump(mode="json"),
    }


def _active_dataset(db: Session, project_id: str) -> Any:
    """Return the active dataset or ask for an upload.

    Args:
        db: Session.
        project_id: Project id.

    Returns:
        Dataset row.
    """
    project = ProjectRepository(db).get(project_id)
    if not project.active_dataset_id:
        raise AppError(
            "Upload an SPSS file before running this. I will not invent a dataset.",
            "missing_dataset",
        )
    return DatasetRepository(db).get(project.active_dataset_id)


def _single_spec(
    fields: dict[str, Any], variables: list[dict[str, Any]], significance: bool
) -> TabSpec:
    """Build a one-table spec. Banner codes come from the dictionary.

    Args:
        fields: Parsed fields.
        variables: Variable dictionary.
        significance: Enable pairwise tests.

    Returns:
        Tab spec.
    """
    by_name = {item["name"]: item for item in variables}
    row = fields["row_variable"]
    banner_name = fields["banner_variable"]
    if row not in by_name or banner_name not in by_name:
        raise AppError(
            "Those variable names are not both in the active dataset.", "missing_variable"
        )
    info = by_name[banner_name]
    labels = info.get("value_labels") or {}
    categories = [
        BannerCategory(label=str(label), codes=[_coerce(code)], order=index)
        for index, (code, label) in enumerate(labels.items())
    ]
    if not categories:
        raise AppError(
            f"'{banner_name}' has no value labels, so I cannot build banner columns. Add labels or a banner definition.",
            "missing_variable",
        )
    weight = fields.get("weight_variable")
    return TabSpec(
        spec_id=new_id(),
        study_defaults=StudyDefaults(weight_variable=weight),
        banners=[
            Banner(
                id="bn1",
                label=str(info.get("label") or banner_name),
                variable_name=banner_name,
                categories=categories,
            )
        ],
        tables=[
            TableSpec(
                id="T001",
                title=f"{row} by {banner_name}",
                row_variable_names=[row],
                banner_ids=["bn1"],
                weight_variable=weight,
                significance=SignificanceSpec(enabled=significance),
            )
        ],
    )


def _crosstab_summary(result: TableResult, fields: dict[str, Any]) -> str:
    """Describe a completed table without inventing a test.

    Args:
        result: Table result.
        fields: Request fields.

    Returns:
        Short summary.
    """
    weight = fields.get("weight_variable") or "no weight"
    tested = any(cell.test_status == "tested" for row in result.rows for cell in row.cells.values())
    significance = (
        "Pairwise letters are shown where the unweighted test was valid."
        if tested
        else "Significance was not shown when the test assumptions were not met."
    )
    return (
        f"Created {result.table_id}: {result.title} using {weight}. "
        f"Values follow the {result.percent_type} percentage definition, with bases stored on each cell. "
        f"{significance}"
    )


def _coerce(code: Any) -> Any:
    """Convert a label key to a number when possible.

    Args:
        code: Label key.

    Returns:
        Int, float, or the original value.
    """
    try:
        number = float(code)
    except (TypeError, ValueError):
        return code
    return int(number) if number.is_integer() else number


def run_spec_book(
    frame: pd.DataFrame, variables: list[dict[str, Any]], spec: TabSpec, dataset_id: str | None
) -> TabBook:
    """Run a canonical spec.

    Args:
        frame: Data.
        variables: Dictionary.
        spec: Tab spec.
        dataset_id: Dataset id.

    Returns:
        Tab book, including an exception for every table that did not run.
    """
    return run_tabspec(frame, variables, spec, dataset_id=dataset_id)


def validation_for_report_artifact(content: dict[str, Any]) -> Any:
    """Recompute the report gate from stored analysis content.

    Args:
        content: Analysis artifact content.

    Returns:
        Validation report.
    """
    report = AnalysisReport.model_validate(content["report"])
    return summarize(validate_report(report, content["result"]))
