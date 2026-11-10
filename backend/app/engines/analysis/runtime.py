"""Entry point the generated analysis script calls inside the sandbox."""

import json
from pathlib import Path

import pandas as pd

from app.engines.analysis.workflow import execute_workflow
from app.schemas.analysis import AnalysisWorkflow


def run_job_files() -> None:
    """Read the job inputs, run the workflow, and write ``result.json``.

    The script and the inputs sit in the job directory. Respondent rows stay
    in the parquet file and are not sent to a model.
    """
    workflow = AnalysisWorkflow.model_validate_json(
        Path("workflow.json").read_text(encoding="utf-8")
    )
    variables = json.loads(Path("variables.json").read_text(encoding="utf-8"))
    frame = pd.read_parquet("input.parquet")
    result = execute_workflow(frame, workflow, variables)
    Path("result.json").write_text(json.dumps(result), encoding="utf-8")
    print("wrote result.json")
