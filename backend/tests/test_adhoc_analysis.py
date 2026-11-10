"""Ad-hoc analysis routing, script checks, and one sandbox rewrite."""

from pathlib import Path

import pandas as pd
import pytest

from app.agents.analysis_coder import AnalysisProgram, attach_program
from app.agents.intent import build_contract
from app.config import Settings
from app.engines.analysis.compile import (
    compile_script,
    ensure_runnable,
    needs_generated_program,
    uses_generated_program,
)
from app.engines.analysis.program_code import validate_program
from app.engines.analysis.program_run import ProgramLaunch, run_program_with_repair
from app.engines.analysis.registry import run_plan
from app.engines.analysis.report import build_report
from app.errors import AppError
from app.sandbox.runner import run_script
from app.schemas.analysis import AnalysisPlan, AnalysisResult, AnalysisStep, AnalysisWorkflow
from app.services.analysis_run import script_kwargs

_COLUMNS = {"satisfaction", "gender"}
_SCRIPT = """
import json
from pathlib import Path

import pandas as pd
from scipy import stats

frame = pd.read_parquet("input.parquet")
left = frame.loc[frame["gender"] == 1, "satisfaction"]
right = frame.loc[frame["gender"] == 2, "satisfaction"]
statistic = float(stats.mannwhitneyu(left, right).statistic)
valid = int(frame[["satisfaction", "gender"]].dropna().shape[0])
payload = {
    "method": "mann_whitney",
    "sample_flow": {"valid_n": valid, "input_n": int(len(frame))},
    "model_estimates": {"comparison": {"u_statistic": statistic}},
    "metrics": {"u_statistic": statistic},
    "diagnostics": {},
    "warnings": [],
    "seed": 42,
}
Path("result.json").write_text(json.dumps(payload), encoding="utf-8")
"""


def _contract(text: str, *, has_dataset: bool = True):
    """Build a contract for an analysis routing check.

    Args:
        text: User message.
        has_dataset: Whether a dataset is loaded.

    Returns:
        Task contract.
    """
    return build_contract(
        task_id="task-1",
        project_id="project-1",
        conversation_id="conversation-1",
        text=text,
        variable_names=["satisfaction", "gender"],
        has_dataset=has_dataset,
    )


def _workflow(program: str = "", *, method: str = "mann_whitney") -> AnalysisWorkflow:
    """Return a one-method plan for a procedure the registry does not implement.

    Args:
        program: Generated script, or empty when the coder has not run.
        method: Method name on the plan.

    Returns:
        Workflow with a method step and a report step.
    """
    return AnalysisWorkflow(
        analysis_id="adhoc",
        objective="Compare satisfaction by gender",
        program=program,
        steps=[
            AnalysisStep(
                step_id="s1",
                kind="method",
                method=method,
                variables=["satisfaction", "gender"],
                reason="The request named a procedure that is not built in.",
            ),
            AnalysisStep(step_id="s2", kind="report", reason="Summarize."),
        ],
    )


def test_mann_whitney_is_analysis_and_a_plain_by_is_a_crosstab() -> None:
    """A named procedure stays an analysis. A row-by-banner request stays a table."""
    mann = _contract("Run a Mann-Whitney test of satisfaction by gender")
    plain = _contract("Q1 by gender")
    missing = _contract("Run a Mann-Whitney test of satisfaction by gender", has_dataset=False)
    blocked = _contract("Run a MaxDiff exercise")
    assert mann.intent == "run_analysis"
    assert mann.missing_required == []
    assert "method" not in mann.provided_fields
    assert plain.intent == "run_crosstab"
    assert missing.intent == "run_analysis"
    assert missing.missing_required == ["dataset"]
    assert blocked.intent == "run_analysis"
    assert blocked.provided_fields["method"] == "maxdiff"
    with pytest.raises(AppError) as caught:
        run_plan(
            pd.DataFrame({"x": [1, 2, 3]}),
            AnalysisPlan(analysis_id="blocked", method="maxdiff"),
        )
    assert caught.value.code == "unsupported_method"


def test_scipy_script_is_accepted_and_a_blocked_script_is_refused() -> None:
    """A scipy import may run. A socket import, open, or an extra column may not."""
    validate_program(_SCRIPT, _COLUMNS, {"satisfaction", "gender"})
    with pytest.raises(AppError) as socket_error:
        validate_program("import socket\n", _COLUMNS, set())
    assert socket_error.value.code == "bad_plan"
    assert "socket" in socket_error.value.message
    with pytest.raises(AppError) as open_error:
        validate_program("handle = open('secret')\n", _COLUMNS, set())
    assert open_error.value.code == "bad_plan"
    with pytest.raises(AppError) as column_error:
        validate_program(
            'import pandas as pd\npd.read_parquet("input.parquet")["age"]\n',
            _COLUMNS | {"age"},
            {"satisfaction"},
        )
    assert column_error.value.code == "bad_plan"
    assert "age" in column_error.value.message


def test_built_in_plan_does_not_run_a_program_field() -> None:
    """A registered method keeps its runner when a script was also filled in."""
    workflow = AnalysisWorkflow(
        analysis_id="corr",
        objective="Correlate x and y",
        program="import socket\n",
        steps=[
            AnalysisStep(
                step_id="s1",
                kind="method",
                method="correlation",
                variables=["x", "y"],
                reason="The request named correlation.",
            ),
            AnalysisStep(step_id="s2", kind="report", reason="Summarize."),
        ],
    )
    assert uses_generated_program(workflow) is False
    assert "run_job_files" in compile_script(workflow)
    ensure_runnable(workflow, {"x", "y"})


async def test_generated_script_runs_and_the_report_matches(
    settings: Settings, tmp_path: Path
) -> None:
    """The sandbox result is the number the report claims."""
    workflow = _workflow(_SCRIPT)
    ensure_runnable(workflow, _COLUMNS)
    frame = pd.DataFrame(
        {
            "satisfaction": [1.0, 2.0, 3.0, 10.0, 11.0, 12.0],
            "gender": [1, 1, 1, 2, 2, 2],
        }
    )

    def launch(script: str) -> ProgramLaunch:
        """Run the script in the labelled sandbox.

        Args:
            script: Generated source.

        Returns:
            Job directory and outcome.
        """
        job = tmp_path / "job"
        job.mkdir(exist_ok=True)
        frame.to_parquet(job / "input.parquet")
        outcome = run_script(settings, job, script, **script_kwargs(settings))
        status = "completed" if outcome["exit_code"] == 0 else "failed"
        return ProgramLaunch(
            job_dir=job,
            outcome={"status": status, "exit_code": outcome["exit_code"]},
            isolation=outcome["isolation"],
            warning=outcome.get("warning"),
            job_id="job",
        )

    async def revise(script: str, error: str) -> str:
        """Fail the test if a correct script is rewritten.

        Args:
            script: Script that ran.
            error: Stderr line.

        Returns:
            Nothing. This path is not used.
        """
        del script, error
        raise AssertionError("rewrite")

    payload, _script, _ran = await run_program_with_repair(
        settings, workflow, _COLUMNS, launch, revise
    )
    result = AnalysisResult.model_validate(payload)
    report = build_report(workflow.objective, result)
    claim = next(item for item in report.claims if item.path == "metrics.u_statistic")
    assert result.metrics["u_statistic"] == pytest.approx(0.0)
    assert claim.stated_value == pytest.approx(0.0)
    assert result.sample_flow["valid_n"] == 6


def test_clarification_does_not_start_a_job() -> None:
    """A missing choice stops before a script is launched."""
    planned = _workflow()
    assert needs_generated_program(planned) is True
    asked = attach_program(
        planned,
        AnalysisProgram(
            status="clarification_needed",
            clarification="Which variable is the outcome?",
            missing_choices=["outcome"],
        ),
    )
    assert needs_generated_program(asked) is False
    with pytest.raises(AppError) as caught:
        ensure_runnable(asked, _COLUMNS)
    assert caught.value.code == "clarification_needed"
    assert "outcome" in caught.value.message
    assert asked.program == ""
    assert asked.steps == []


async def test_failing_script_is_rewritten_once_and_then_not_published(
    settings: Settings, tmp_path: Path
) -> None:
    """The second sandbox failure raises, and no result file is published."""
    first = 'import json\nraise RuntimeError("analysis failed")\n'
    second = 'import json\nraise RuntimeError("still failed")\n'
    workflow = _workflow(first)
    ensure_runnable(workflow, _COLUMNS)
    calls: list[str] = []

    def launch(script: str) -> ProgramLaunch:
        """Run a script that exits with an error.

        Args:
            script: Generated source.

        Returns:
            Failed job.
        """
        calls.append(script)
        job = tmp_path / f"job{len(calls)}"
        outcome = run_script(settings, job, script, **script_kwargs(settings))
        return ProgramLaunch(
            job_dir=job,
            outcome={"status": "failed", "exit_code": outcome["exit_code"]},
            isolation=outcome["isolation"],
            job_id=job.name,
        )

    async def revise(script: str, error: str) -> str:
        """Return a second script that also fails.

        Args:
            script: Script that failed.
            error: Last stderr line.

        Returns:
            Replacement script.
        """
        assert "analysis failed" in error
        assert "raise RuntimeError" in script
        return second

    with pytest.raises(AppError) as caught:
        await run_program_with_repair(settings, workflow, _COLUMNS, launch, revise)
    assert caught.value.code == "sandbox_failed"
    assert len(calls) == 2
    assert not (tmp_path / "job2" / "result.json").exists()
