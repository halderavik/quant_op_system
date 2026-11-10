"""Plan an analysis from the dataset profile and run that plan in the sandbox."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.agents.analysis_coder import attach_program, propose_program, revise_program
from app.agents.analysis_planner import phrase_findings, propose_workflow
from app.config import Settings
from app.engines.analysis.compile import (
    compile_script,
    direct_workflow,
    ensure_runnable,
    needs_generated_program,
    referenced_names,
    render_plan,
    uses_generated_program,
)
from app.engines.analysis.profile import column_briefs
from app.engines.analysis.program_run import ProgramLaunch, run_program_with_repair
from app.engines.analysis.report import build_report, workflow_summary
from app.engines.analysis.workbook import workbook_bytes
from app.engines.invariants import summarize, validate_report
from app.errors import AppError
from app.repositories.records import ArtifactRepository, ProjectRepository
from app.sandbox.runner import docker_available, run_script
from app.schemas.analysis import AnalysisResult, AnalysisWorkflow
from app.services.execute import _active_dataset, load_frame
from app.services.jobs import execute_job
from app.services.storage import Storage
from app.services.stored_files import _write_export

_BLOCKED = {"maxdiff", "max-diff", "conjoint", "cbc"}
_SLIM_IMAGE = "python:3.12-slim"


def analysis_forces_subprocess(settings: Settings) -> bool:
    """Return whether the analysis script must use the app interpreter.

    Args:
        settings: Application settings.

    Returns:
        True when Docker is down or the image is the slim default, which has
        no pandas or scikit-learn.
    """
    image = settings.sandbox_image.strip()
    if image in {"", _SLIM_IMAGE}:
        return True
    return not docker_available()


def backend_root() -> Path:
    """Return the backend directory that contains the ``app`` package.

    Returns:
        Absolute backend path.
    """
    return Path(__file__).resolve().parents[2]


def script_kwargs(settings: Settings) -> dict[str, Any]:
    """Return sandbox options that let the analysis script import the studio.

    Args:
        settings: Application settings.

    Returns:
        Keyword arguments for ``run_script`` and ``execute_job``.
    """
    backend = backend_root()
    force = analysis_forces_subprocess(settings)
    kwargs: dict[str, Any] = {
        "read_roots": [backend],
        "pythonpath": str(backend),
        "force_subprocess": force,
        "script_name": "analysis.py",
    }
    if not force:
        kwargs["extra_mounts"] = [(backend / "app", "/studio/app")]
        kwargs["extra_env"] = {"PYTHONPATH": "/studio"}
    return kwargs


def require_analysis_output(job_dir: Path, outcome: dict[str, Any]) -> dict[str, Any]:
    """Load ``result.json`` or refuse to publish.

    Args:
        job_dir: Job directory.
        outcome: Status and exit code from the runner.

    Returns:
        Parsed result.

    Raises:
        AppError: The script failed or wrote no result.
    """
    if outcome.get("status") in {"failed", "cancelled"} or outcome.get("exit_code") not in (
        0,
        None,
    ):
        message = "The analysis script failed in the sandbox. No report was published."
        stderr = job_dir / "stderr.txt"
        if stderr.exists():
            lines = [
                line.strip()
                for line in stderr.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if lines:
                message = f"{message} {lines[-1][:300]}"
        raise AppError(message, "sandbox_failed")
    path = job_dir / "result.json"
    if not path.exists():
        raise AppError(
            "The analysis script did not write a result. No report was published.",
            "sandbox_failed",
        )
    return json.loads(path.read_text(encoding="utf-8"))


def run_compiled_workflow(
    settings: Settings,
    job_dir: Path,
    frame: Any,
    workflow: AnalysisWorkflow,
    variables: list[dict[str, Any]],
) -> dict[str, Any]:
    """Write the job inputs and run the compiled script.

    Args:
        settings: Application settings.
        job_dir: Directory for the script, inputs, and result.
        frame: Respondent data.
        workflow: Plan.
        variables: Variable dictionary.

    Returns:
        Parsed ``result.json``.

    Raises:
        AppError: The script failed or wrote no result.
    """
    script = compile_script(workflow)
    job_dir.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(job_dir / "input.parquet")
    (job_dir / "workflow.json").write_text(workflow.model_dump_json(), encoding="utf-8")
    (job_dir / "variables.json").write_text(json.dumps(variables, default=str), encoding="utf-8")
    outcome = run_script(settings, job_dir, script, **script_kwargs(settings))
    return require_analysis_output(job_dir, outcome)


async def run_planned_analysis(
    db: Session,
    storage: Storage,
    settings: Settings,
    project_id: str,
    *,
    request: str,
    hints: dict[str, Any],
    session_id: str,
    on_stage: Any,
) -> dict[str, Any]:
    """Plan from the dataset profile, run the script, and publish the downloads.

    Args:
        db: Session.
        storage: Storage service.
        settings: Application settings.
        project_id: Project id.
        request: User text.
        hints: Roles parsed from the request. They are hints, not a finished plan.
        session_id: SDK session id.
        on_stage: Records a chat stage. Called with one message string.

    Returns:
        Summary payload.

    Raises:
        AppError: The method is blocked, the plan cannot run, or the script fails.
    """
    method = str(hints.get("method") or "").lower().replace(" ", "_")
    if method in _BLOCKED:
        raise AppError(
            "MaxDiff and conjoint are out of scope for this studio. No alternative model was run.",
            "unsupported_method",
        )
    on_stage("Reading the dataset")
    dataset = _active_dataset(db, project_id)
    frame = load_frame(storage, dataset)
    briefs, omitted = column_briefs(frame, dataset.variables)
    columns = {str(item["name"]) for item in dataset.variables}
    on_stage("Writing the analysis plan")
    workflow = direct_workflow(request, hints, dataset.id)
    if workflow is None:
        workflow = await propose_workflow(
            settings,
            request=request,
            briefs=briefs,
            hints=hints,
            omitted=omitted,
            dataset_id=dataset.id,
            session_id=session_id,
        )
    if needs_generated_program(workflow):
        on_stage("Writing the analysis script")
        program = await propose_program(
            settings,
            request=request,
            briefs=briefs,
            omitted=omitted,
            workflow=workflow,
            session_id=session_id,
        )
        workflow = attach_program(workflow, program)
    ensure_runnable(workflow, columns)
    on_stage("Running the analysis in the sandbox")
    script = compile_script(workflow)
    project = ProjectRepository(db).get(project_id)
    store_traces = bool((project.study_context or {}).get("store_traces"))
    with tempfile.TemporaryDirectory() as tmp:
        parquet = Path(tmp) / "input.parquet"
        frame.to_parquet(parquet)
        if uses_generated_program(workflow):
            payload, script, ran = await _run_generated(
                db,
                storage,
                settings,
                project_id,
                workflow,
                columns,
                request=request,
                session_id=session_id,
                store_traces=store_traces,
                parquet=parquet,
                variables=dataset.variables,
                on_stage=on_stage,
            )
            isolation, warning, job_id = ran.isolation, ran.warning, ran.job_id
        else:
            job = execute_job(
                db,
                storage,
                settings,
                project_id,
                kind="analysis",
                script=script,
                inputs={
                    "workflow.json": workflow.model_dump_json(),
                    "variables.json": json.dumps(dataset.variables, default=str),
                },
                binaries={"input.parquet": parquet},
                prompt=request,
                store_traces=store_traces,
                **script_kwargs(settings),
            )
            payload = require_analysis_output(
                storage.project_root(project_id) / "jobs" / job.id,
                {"status": job.status, "exit_code": (job.manifest or {}).get("exit_code")},
            )
            isolation, warning, job_id = job.isolation, job.warning, job.id
    if payload.get("resolved_workflow"):
        workflow = AnalysisWorkflow.model_validate(payload["resolved_workflow"])
    if "run_job_files" not in script:
        workflow = workflow.model_copy(update={"program": script.strip()})
    on_stage("Writing the summary")
    payload["script"] = script
    result = AnalysisResult.model_validate(payload)
    report = build_report(workflow.objective, result)
    report = await phrase_findings(settings, report, session_id=session_id)
    checks = validate_report(report, result.model_dump(mode="json"))
    gate = summarize(checks)
    plan_text = render_plan(workflow, _checked_counts(briefs, referenced_names(workflow)))
    book = workbook_bytes(workflow, payload, report)
    plan_id = _write_export(
        db, storage, project_id, "analysis_plan.md", plan_text.encode("utf-8"), "text/markdown"
    )
    script_id = _write_export(
        db, storage, project_id, "analysis.py", script.encode("utf-8"), "text/x-python"
    )
    workbook_id = _write_export(
        db,
        storage,
        project_id,
        "analysis_output.xlsx",
        book,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    revision = ArtifactRepository(db).create(
        project_id=project_id,
        artifact_type="analysis",
        name=report.title,
        content={
            "workflow": workflow.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
            "report": report.model_dump(mode="json"),
            "plan_file_id": plan_id,
            "script_file_id": script_id,
            "workbook_file_id": workbook_id,
            "provenance": {
                "isolation": isolation,
                "warning": warning,
                "job_id": job_id,
                "dataset_id": dataset.id,
                "seed": workflow.random_seed,
            },
        },
        content_schema="analysis/2",
        created_by="analysis",
        validation_status=gate.status,
    )
    status = (
        "completed_with_warnings" if result.warnings or gate.status != "passed" else "completed"
    )
    return {
        "summary": workflow_summary(
            workflow.objective,
            [step.kind for step in workflow.steps],
            result.sample_flow.get("valid_n"),
        ),
        "status": status,
        "artifact_id": revision.artifact_id,
        "version": revision.version,
        "warnings": result.warnings,
        "validation": gate.model_dump(mode="json"),
    }


async def _run_generated(
    db: Session,
    storage: Storage,
    settings: Settings,
    project_id: str,
    workflow: AnalysisWorkflow,
    columns: set[str],
    *,
    request: str,
    session_id: str,
    store_traces: bool,
    parquet: Path,
    variables: list[dict[str, Any]],
    on_stage: Any,
) -> tuple[dict[str, Any], str, ProgramLaunch]:
    """Run a generated script in the sandbox, with one rewrite after a failure.

    Args:
        db: Session.
        storage: Storage service.
        settings: Application settings.
        project_id: Project id.
        workflow: Plan whose program is the script.
        columns: Dataset column names.
        request: User text. Stored only when traces are enabled.
        session_id: SDK session id.
        store_traces: Project trace setting.
        parquet: Respondent snapshot copied into the job.
        variables: Variable dictionary written next to the snapshot.
        on_stage: Records a chat stage. Called with one message string.

    Returns:
        Parsed result, the script that produced it, and the successful launch.

    Raises:
        AppError: The script fails twice, or the rewrite is rejected.
    """

    def launch(source: str) -> ProgramLaunch:
        """Start one sandbox job for the generated script.

        Args:
            source: Script source.

        Returns:
            Job directory and outcome.
        """
        job = execute_job(
            db,
            storage,
            settings,
            project_id,
            kind="analysis",
            script=source,
            inputs={
                "workflow.json": workflow.model_dump_json(),
                "variables.json": json.dumps(variables, default=str),
            },
            binaries={"input.parquet": parquet},
            prompt=request,
            store_traces=store_traces,
            **script_kwargs(settings),
        )
        return ProgramLaunch(
            job_dir=storage.project_root(project_id) / "jobs" / job.id,
            outcome={
                "status": job.status,
                "exit_code": (job.manifest or {}).get("exit_code"),
            },
            isolation=job.isolation,
            warning=job.warning,
            job_id=job.id,
        )

    async def revise(source: str, error: str) -> str:
        """Ask for one rewrite. The error line contains no respondent rows.

        Args:
            source: Script that failed.
            error: Last stderr line.

        Returns:
            Replacement script.
        """
        on_stage("Rewriting the analysis script")
        return await revise_program(
            settings,
            script=source,
            error=error,
            columns=sorted(referenced_names(workflow)),
            objective=workflow.objective,
            session_id=session_id,
        )

    return await run_program_with_repair(settings, workflow, columns, launch, revise)


def _checked_counts(briefs: list[dict[str, Any]], names: list[str]) -> list[dict[str, Any]]:
    """Return missing counts for the columns the plan named.

    Args:
        briefs: Column briefs.
        names: Variable names.

    Returns:
        Count rows for the plan download.
    """
    by_name = {str(item["name"]): item for item in briefs}
    rows = []
    for name in names:
        item = by_name.get(name)
        if item is None:
            continue
        rows.append(
            {
                "name": name,
                "nonmissing_n": item["nonmissing_n"],
                "missing_n": item["missing_n"],
            }
        )
    return rows
