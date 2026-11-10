"""Run a generated analysis script, and rewrite it once if the sandbox rejects it."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings
from app.engines.analysis.compile import compile_script, referenced_names
from app.engines.analysis.program_code import validate_program
from app.errors import AppError
from app.schemas.analysis import AnalysisWorkflow


@dataclass
class ProgramLaunch:
    """One sandbox attempt for a generated analysis script."""

    job_dir: Path
    outcome: dict[str, Any]
    isolation: str | None = None
    warning: str | None = None
    job_id: str = ""


async def run_program_with_repair(
    settings: Settings,
    workflow: AnalysisWorkflow,
    columns: set[str],
    launch: Callable[[str], ProgramLaunch],
    revise: Callable[[str, str], Awaitable[str]],
) -> tuple[dict[str, Any], str, ProgramLaunch]:
    """Run the generated script. On failure, rewrite it once and run that rewrite.

    Args:
        settings: Application settings. Kept so the call matches the other runners.
        workflow: Plan whose program is the script.
        columns: Dataset column names.
        launch: Starts one sandbox job and returns its directory and outcome.
        revise: Returns a new script from the failed source and the last stderr line.

    Returns:
        Parsed result, the script that produced it, and the launch that succeeded.

    Raises:
        AppError: The rewrite is empty or still illegal, or the second run fails.
            Nothing is published in that case.
    """
    del settings
    script = compile_script(workflow)
    ran = launch(script)
    try:
        payload = _require(ran)
    except AppError as exc:
        if exc.code != "sandbox_failed":
            raise
        revised = (await revise(script, _stderr_tail(ran.job_dir))).strip()
        if not revised:
            raise AppError(
                "The analysis script failed and the rewrite was empty. No report was published.",
                "sandbox_failed",
            ) from exc
        checked = workflow.model_copy(update={"program": revised})
        validate_program(revised, columns, set(referenced_names(checked)))
        script = compile_script(checked)
        ran = launch(script)
        payload = _require(ran)
    return payload, script, ran


def _require(ran: ProgramLaunch) -> dict[str, Any]:
    """Load result.json from one launch.

    Args:
        ran: Sandbox attempt.

    Returns:
        Parsed result.

    Raises:
        AppError: The script failed or wrote no result.
    """
    from app.services.analysis_run import require_analysis_output

    return require_analysis_output(ran.job_dir, ran.outcome)


def _stderr_tail(job_dir: Path) -> str:
    """Return the last stderr line, trimmed.

    Args:
        job_dir: Job directory.

    Returns:
        Last nonempty line, or an empty string when stderr was not written.
    """
    path = job_dir / "stderr.txt"
    if not path.exists():
        return ""
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return ""
    return lines[-1][:500]
