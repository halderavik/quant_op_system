"""Persist sandbox runs as job rows and honor cancel, time, and memory settings."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Job
from app.repositories.records_files import JobRepository
from app.sandbox.runner import cancel_process, run_script
from app.services.storage import Storage

_TERMINAL = {"completed", "failed", "cancelled"}


def execute_job(
    db: Session,
    storage: Storage,
    settings: Settings,
    project_id: str,
    *,
    kind: str,
    script: str,
    inputs: dict[str, str] | None = None,
    prompt: str | None = None,
    store_traces: bool = False,
    binaries: dict[str, Path] | None = None,
    script_name: str = "main.py",
    read_roots: list[Path] | None = None,
    pythonpath: str | None = None,
    force_subprocess: bool = False,
    extra_mounts: list[tuple[Path, str]] | None = None,
    extra_env: dict[str, str] | None = None,
) -> Job:
    """Insert one job, run the script, and store the outcome on that row.

    Args:
        db: Session.
        storage: Project storage.
        settings: Application settings. The API key is not written onto the job.
        project_id: Project id.
        kind: Job kind such as ``chart`` or ``sandbox``.
        script: Python source executed by the sandbox runner.
        inputs: Basename-to-text files written into the job directory before the run.
        prompt: User text. Stored only when ``store_traces`` is true.
        store_traces: When false, prompt text is omitted from the row and logs.
        binaries: Basename-to-path files copied into the job directory.
        script_name: Script filename inside the job directory.
        read_roots: Extra directories the subprocess may read.
        pythonpath: ``PYTHONPATH`` for the subprocess.
        force_subprocess: Skip Docker and use the app interpreter.
        extra_mounts: Read-only mounts used only by Docker.
        extra_env: Extra Docker environment entries.

    Returns:
        The same job row, updated to a terminal status.
    """
    repo = JobRepository(db)
    job = repo.add(
        project_id=project_id,
        kind=kind,
        status="running",
        manifest={
            "timeout_seconds": settings.sandbox_timeout_seconds,
            "memory_mb": settings.sandbox_memory_mb,
        },
    )
    job_dir = storage.project_root(project_id) / "jobs" / job.id
    job_dir.mkdir(parents=True, exist_ok=True)
    for name, text in (inputs or {}).items():
        (job_dir / name).write_text(text, encoding="utf-8")
    for name, source in (binaries or {}).items():
        shutil.copyfile(source, job_dir / name)
    result = run_script(
        settings,
        job_dir,
        script,
        timeout=settings.sandbox_timeout_seconds,
        job_id=job.id,
        script_name=script_name,
        read_roots=read_roots,
        pythonpath=pythonpath,
        force_subprocess=force_subprocess,
        extra_mounts=extra_mounts,
        extra_env=extra_env,
    )
    stdout = _scrub(result.get("stdout") or "", prompt, store_traces)
    stderr = _scrub(result.get("stderr") or "", prompt, store_traces)
    (job_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
    (job_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
    db.refresh(job)
    if job.status != "cancelled":
        if result.get("timed_out"):
            job.status = "failed"
        elif result.get("exit_code") == 0:
            job.status = "completed"
        else:
            job.status = "failed"
    job.isolation = result.get("isolation") or job.isolation
    job.warning = result.get("warning")
    job.log_relpath = f"jobs/{job.id}/stdout.txt"
    manifest: dict[str, Any] = {
        "timeout_seconds": settings.sandbox_timeout_seconds,
        "memory_mb": settings.sandbox_memory_mb,
        "exit_code": result.get("exit_code"),
        "timed_out": bool(result.get("timed_out")),
        "stderr_relpath": f"jobs/{job.id}/stderr.txt",
        "file_ids": [],
    }
    if store_traces and prompt:
        (job_dir / "request.txt").write_text(prompt, encoding="utf-8")
        manifest["prompt"] = prompt
        manifest["request_relpath"] = f"jobs/{job.id}/request.txt"
    job.manifest = manifest
    job.updated_at = _now()
    db.flush()
    return job


def cancel_job(db: Session, job_id: str) -> Job:
    """Mark a queued or running job cancelled without inserting another row.

    Args:
        db: Session.
        job_id: Job id.

    Returns:
        The existing job row.
    """
    job = JobRepository(db).get(job_id)
    if job.status not in _TERMINAL:
        cancel_process(job.id)
        job.status = "cancelled"
        job.updated_at = _now()
        db.flush()
    return job


def job_payload(job: Job) -> dict[str, Any]:
    """Serialize a job for the API.

    Args:
        job: Job row.

    Returns:
        Public job dictionary. Prompt text is included only when it was stored.
    """
    return {
        "id": job.id,
        "project_id": job.project_id,
        "kind": job.kind,
        "status": job.status,
        "isolation": job.isolation,
        "warning": job.warning,
        "manifest": job.manifest or {},
        "log_relpath": job.log_relpath,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


def _now() -> datetime:
    """Return the current UTC time.

    Returns:
        Timezone-aware timestamp.
    """
    return datetime.now(timezone.utc)


def _scrub(text: str, prompt: str | None, store_traces: bool) -> str:
    """Remove the user prompt from a log when traces are off.

    Args:
        text: Log text.
        prompt: User prompt.
        store_traces: Whether prompt text may remain.

    Returns:
        Log text.
    """
    if store_traces or not prompt:
        return text
    return text.replace(prompt, "")
