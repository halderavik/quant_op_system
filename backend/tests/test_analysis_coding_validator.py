"""Analysis plugins, open-end frequencies, and the validator gate."""

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from app.engines.analysis.registry import run_plan
from app.engines.analysis.report import build_report, claims_match_result
from app.engines.coding_agg import aggregate, merge_checkpoint
from app.engines.invariants import (
    allow_repair,
    semantic_interpretation,
    summarize,
    validate_export,
    validate_report,
)
from app.errors import AppError
from app.schemas.analysis import AnalysisPlan, ReportClaim, VariableRole
from app.schemas.coding import Codeframe, CodeNode, CodingAssignment, HumanOverride, NetNode
from app.services.documents import aggregate_saved_coding
from tests.conftest import create_project


def _logistic_frame() -> pd.DataFrame:
    """Synthetic binary outcome with a known seed.

    Returns:
        Analysis frame.
    """
    rng = np.random.default_rng(42)
    trust = rng.normal(size=300)
    age = rng.normal(size=300)
    probability = 1 / (1 + np.exp(-(-0.3 + 1.2 * trust + 0.1 * age)))
    outcome = rng.binomial(1, probability)
    return pd.DataFrame({"purchase": outcome, "trust": trust, "age": age})


def test_logistic_matches_statsmodels_and_blocks_missing_roles() -> None:
    """Coefficients match a direct statsmodels fit. Missing roles do not invent a dependent variable."""
    frame = _logistic_frame()
    plan = AnalysisPlan(
        analysis_id="an1",
        method="binary_logistic_regression",
        dependent=VariableRole(name="purchase", role="dependent"),
        predictors=["trust", "age"],
        random_seed=42,
    )
    result = run_plan(frame, plan)
    direct = sm.Logit(
        frame["purchase"], sm.add_constant(frame[["trust", "age"]], has_constant="add")
    ).fit(disp=False)
    assert result.model_estimates["trust"]["coefficient"] == pytest.approx(
        float(direct.params["trust"]), rel=1e-6
    )
    assert result.sample_flow["valid_n"] == 300
    assert "statsmodels" in result.script
    with pytest.raises(AppError) as caught:
        run_plan(frame, AnalysisPlan(analysis_id="an2", method="binary_logistic_regression"))
    assert caught.value.code == "missing_roles"


def test_maxdiff_is_refused() -> None:
    """MaxDiff does not run a substitute model."""
    with pytest.raises(AppError) as caught:
        run_plan(pd.DataFrame({"x": [1, 2, 3]}), AnalysisPlan(analysis_id="an3", method="maxdiff"))
    assert caught.value.code == "unsupported_method"


def test_clustering_matches_sklearn_seed() -> None:
    """Cluster sizes sum to N and labels match sklearn with the same seed."""
    rng = np.random.default_rng(1)
    frame = pd.DataFrame(
        {
            "x": np.concatenate([rng.normal(-2, 0.3, 40), rng.normal(2, 0.3, 40)]),
            "y": np.concatenate([rng.normal(0, 0.3, 40), rng.normal(0, 0.3, 40)]),
        }
    )
    plan = AnalysisPlan(
        analysis_id="an4",
        method="clustering",
        variables=["x", "y"],
        random_seed=7,
        options={"k": 2},
    )
    result = run_plan(frame, plan)
    sizes = result.model_estimates["sizes"]
    assert sum(sizes.values()) == result.sample_flow["valid_n"]
    scaled = StandardScaler().fit_transform(frame)
    expected = KMeans(n_clusters=2, random_state=7, n_init=10).fit_predict(scaled)
    assert result.descriptive["labels"] == [int(label) for label in expected]


def test_coding_nets_blanks_and_overrides() -> None:
    """Nets dedupe respondents, blanks stay out of sentiment, and invented codes are rejected."""
    frame = Codeframe(
        codeframe_id="cf1",
        response_variable="Q_OE",
        respondent_id_variable="respondent_id",
        codes=[
            CodeNode(id="C01", label="Quality"),
            CodeNode(id="C02", label="Service"),
        ],
        nets=[NetNode(id="N01", label="Any", child_ids=["C01", "C02"])],
    )
    rows = []
    for index in range(30):
        if index < 2:
            text, codes, sentiment = "", [], None
        elif index == 2:
            text, codes, sentiment = "n/a", [], None
        elif index % 5 == 0:
            text, codes, sentiment = "Good quality but slow service", ["C01", "C02"], "mixed"
        elif index % 2 == 0:
            text, codes, sentiment = "Good quality", ["C01"], "positive"
        else:
            text, codes, sentiment = "Slow service", ["C02"], "negative"
        rows.append(
            CodingAssignment(
                respondent_id=str(index),
                source_row_id=index,
                response_text=text,
                assigned_code_ids=codes,
                sentiment=sentiment,
                substantive=bool(text.strip()) and text.lower() != "n/a",
            )
        )
    report = aggregate(frame, rows, weights={str(index): 1.0 for index in range(30)})
    net = next(item for item in report.frequencies if item.id == "N01")
    quality = next(item for item in report.frequencies if item.id == "C01")
    assert report.nonsubstantive_n == 3
    assert "positive" in report.sentiment_counts or "negative" in report.sentiment_counts
    assert net.unweighted_respondents <= report.substantive_n
    assert net.unweighted_respondents >= quality.unweighted_respondents
    rows[4].human_overrides = HumanOverride(code_ids=["C02"], sentiment="negative")
    updated = aggregate(frame, rows)
    assert updated.frequencies
    bad = rows[5].model_copy(deep=True)
    bad.assigned_code_ids = ["NO_SUCH"]
    with pytest.raises(AppError):
        aggregate(frame, [bad])
    cleaned_report, cleaned_rows = aggregate_saved_coding(frame, [bad])
    assert cleaned_rows[0].assigned_code_ids == []
    assert cleaned_rows[0].review_required is True
    assert cleaned_report.substantive_n == 1
    first = rows[:10]
    retry = merge_checkpoint(first, rows)
    assert len(retry) == 30
    assert len({row.source_row_id for row in retry}) == 30


def test_validator_rejects_a_tampered_percentage() -> None:
    """A claim that does not match the computed coefficient fails the gate."""
    frame = _logistic_frame()
    result = run_plan(
        frame,
        AnalysisPlan(
            analysis_id="an5",
            method="linear_regression",
            dependent=VariableRole(name="purchase", role="dependent"),
            predictors=["trust", "age"],
        ),
    )
    report = build_report("Purchase", result)
    assert claims_match_result(report, result.model_dump(mode="json")) == []
    tampered = report.model_copy(deep=True)
    tampered.claims[0] = ReportClaim(
        path=tampered.claims[0].path,
        stated_value=999,
        sentence="The coefficient is 999.",
    )
    tampered.rendered = "The coefficient is 999."
    checks = validate_report(tampered, result.model_dump(mode="json"))
    gate = summarize(checks, task_id="t1")
    assert gate.status == "failed"
    assert "999" not in gate.checks[0].details or gate.checks[0].status == "failed"
    missing = validate_export(None)
    assert missing.status == "failed"


@pytest.mark.asyncio
async def test_code_batch_skips_checkpointed_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """A retried batch does not duplicate rows, and unknown codes are removed."""
    from app.agents.coding_agent import CodingBatch, code_batch
    from app.config import Settings

    frame = Codeframe(
        codeframe_id="cf2",
        response_variable="Q_OE",
        respondent_id_variable="respondent_id",
        codes=[CodeNode(id="C01", label="Quality")],
        nets=[],
    )
    incoming = CodingAssignment(
        respondent_id="1",
        source_row_id=1,
        response_text="Good",
        assigned_code_ids=["C01", "MADE_UP"],
        sentiment="positive",
    )
    existing = CodingAssignment(
        respondent_id="1",
        source_row_id=1,
        response_text="Good",
        assigned_code_ids=["C01"],
        sentiment="positive",
    )

    async def _fake(*_args, **_kwargs):
        return CodingBatch(assignments=[incoming])

    monkeypatch.setattr("app.agents.coding_agent.run_structured", _fake)
    settings = Settings(
        openai_api_key="sk-test", storage_root=".", cors_origins="http://localhost:5173"
    )
    merged, report = await code_batch(settings, frame, "batch", "session", existing=[existing])
    assert len(merged) == 1
    assert report.substantive_n == 1


def test_semantic_warning_does_not_rewrite_a_number() -> None:
    """Causal wording is flagged, and a numeric failure is not auto-repaired."""
    warning = semantic_interpretation("This proves that trust causes purchase.")
    assert warning[0].status == "failed"
    assert warning[0].severity == "warning"
    assert allow_repair(0, numeric_failure=True) is False
    assert allow_repair(2, numeric_failure=False) is False
    assert allow_repair(1, numeric_failure=False) is True


def test_analysis_chat_asks_for_roles(client) -> None:
    """The chat asks for a dependent variable instead of choosing one."""
    project = create_project(client)
    response = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": "Run a logistic regression"},
    )
    task = client.get(f"/api/tasks/{response.json()['task_id']}").json()
    assert task["status"] == "clarification_needed"
    messages = client.get(f"/api/conversations/{project['conversation_id']}/messages").json()
    assert "dependent" in messages[-1]["content"].lower()
