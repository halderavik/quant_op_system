"""Context-aware routing and the keyword fallback."""

from unittest.mock import patch

from app.agents.intent import build_contract
from app.agents.route_context import project_snapshot
from app.agents.router import RouteDecision, choose_route
from app.config import Settings
from app.errors import AppError
from app.schemas.project import TaskContract

_PCA = (
    "can you run a PCA to reduce the dimension of then run a K-means clustering "
    "with 4 segments. Then build the crosstab using the profiling variables and "
    "segmentation variable then write a report"
)
_SPEC = "generate cross-tabs based on the specs"
_BRIEF = "Audience: Adults 18+\nObjectives:\n- Track awareness\n"


def _contract(
    text: str, settings_intent: str | None = None, reason: str = "", **kwargs
) -> TaskContract:
    """Build a contract for one message.

    Args:
        text: User message.
        settings_intent: Intent supplied by a route decision.
        reason: Route reason.
        **kwargs: Flags passed to the contract builder.

    Returns:
        Task contract.
    """
    return build_contract(
        task_id="task-1",
        project_id="project-1",
        conversation_id="conversation-1",
        text=text,
        variable_names=kwargs.pop("variable_names", ["Q1", "gender"]),
        has_dataset=kwargs.pop("has_dataset", False),
        chosen_intent=settings_intent,
        route_reason=reason,
        **kwargs,
    )


def _snapshot() -> dict:
    """Return a snapshot that already has a tab spec.

    Returns:
        Project snapshot.
    """
    return project_snapshot(
        artifact_versions_by_type={"tabspec": 1, "questionnaire": 2, "note": 9},
        dataset_active=True,
        variable_names=["Q1", "gender"],
        previous_reply="The tab book is in the panel.",
        previous_intent="run_saved_tabspec",
        previous_status="completed",
        objectives=["Segment buyers"],
    )


def test_snapshot_lists_artifacts_and_omits_rows() -> None:
    """The route packet names artifacts, the last task, and variables, not rows."""
    names = ["Q1", "gender"] + [f"V{index}" for index in range(50)]
    snapshot = project_snapshot(
        artifact_versions_by_type={"tabspec": 1, "questionnaire": 2, "note": 9},
        dataset_active=True,
        variable_names=names,
        previous_reply="I still need the features. " + ("row-99 " * 80),
        previous_intent="run_analysis",
        previous_status="clarification_needed",
        objectives=["Segment buyers"],
    )
    assert snapshot["artifacts"] == {"tabspec": 1, "questionnaire": 2}
    assert snapshot["previous_intent"] == "run_analysis"
    assert snapshot["previous_status"] == "clarification_needed"
    assert snapshot["variable_names"][:2] == ["Q1", "gender"]
    assert snapshot["variable_count"] == 52
    assert len(snapshot["variable_names"]) == 40
    assert len(snapshot["previous_reply"]) == 500
    assert "content" not in snapshot
    assert "rows" not in snapshot


async def test_analysis_decision_beats_a_saved_spec(settings: Settings) -> None:
    """A stubbed analysis route wins when the words also say crosstab."""
    keyword = _contract(_PCA, has_dataset=True, has_tabspec=True)
    assert keyword.intent == "run_saved_tabspec"

    async def _analysis(*_args: object, **kwargs: object) -> RouteDecision:
        instructions = str(kwargs["instructions"])
        assert "run_analysis" in instructions
        assert "tab spec" in instructions
        assert "tabspec" in str(kwargs["prompt"])
        return RouteDecision(intent="run_analysis", reason="PCA and a segment profile.")

    with patch("app.agents.router.run_structured", _analysis):
        decision = await choose_route(
            settings, text=_PCA, snapshot=_snapshot(), session_id="route-1"
        )
    assert decision is not None
    routed = _contract(
        _PCA,
        decision.intent,
        decision.reason,
        has_dataset=True,
        has_tabspec=True,
    )
    assert routed.intent == "run_analysis"
    assert routed.specialist == "analysis"
    assert routed.defaults_used["route_reason"] == "PCA and a segment profile."
    assert routed.missing_required == []


async def test_spec_decision_runs_the_saved_book(settings: Settings) -> None:
    """A stubbed saved-spec route does not ask for one row and one banner."""

    async def _spec(*_args: object, **_kwargs: object) -> RouteDecision:
        return RouteDecision(intent="run_saved_tabspec", reason="The user pointed at the spec.")

    with patch("app.agents.router.run_structured", _spec):
        decision = await choose_route(
            settings, text=_SPEC, snapshot=_snapshot(), session_id="route-1"
        )
    assert decision is not None
    routed = _contract(
        _SPEC,
        decision.intent,
        decision.reason,
        has_dataset=True,
        has_tabspec=True,
    )
    assert routed.intent == "run_saved_tabspec"
    assert routed.missing_required == []


async def test_failed_route_call_uses_the_keyword_contract(settings: Settings) -> None:
    """A model error leaves the keyword order in place."""

    async def _fail(*_args: object, **_kwargs: object) -> RouteDecision:
        raise AppError("OPENAI_API_KEY is not set.", "missing_api_key", 503)

    with patch("app.agents.router.run_structured", _fail):
        decision = await choose_route(
            settings, text=_PCA, snapshot=_snapshot(), session_id="route-1"
        )
    assert decision is None
    fallback = _contract(_PCA, has_dataset=True, has_tabspec=True)
    assert fallback.intent == "run_saved_tabspec"


async def test_product_locks_do_not_call_the_model(settings: Settings) -> None:
    """Decipher, a pasted brief, and MaxDiff stay on their fixed routes."""
    called = False

    async def _spy(*_args: object, **_kwargs: object) -> RouteDecision:
        nonlocal called
        called = True
        return RouteDecision(intent="general_task", reason="should not run")

    with patch("app.agents.router.run_structured", _spy):
        decipher = await choose_route(
            settings,
            text="program this survey in decipher",
            snapshot=_snapshot(),
            session_id="route-1",
        )
        brief = await choose_route(
            settings, text=_BRIEF, snapshot=_snapshot(), session_id="route-1"
        )
        blocked = await choose_route(
            settings, text="Run a MaxDiff exercise", snapshot=_snapshot(), session_id="route-1"
        )
    assert called is False
    assert decipher is not None and decipher.intent == "program_decipher"
    assert brief is not None and brief.intent == "create_questionnaire"
    assert blocked is not None and blocked.intent == "run_analysis"
    analysis = _contract("Run a MaxDiff exercise", blocked.intent, blocked.reason)
    assert analysis.intent == "run_analysis"
    assert analysis.provided_fields["method"] == "maxdiff"
    assert analysis.missing_required == []


def test_fraud_request_is_cleaning_not_coding() -> None:
    """Open-end fraud stays on cleaning, and a coding request stays on coding."""
    fraud = _contract(
        "recommend fraud respondents, including the open ends",
        has_dataset=True,
    )
    assert fraud.intent == "clean_data"
    assert fraud.specialist == "cleaning"
    assert fraud.missing_required == []
    coding = _contract("code the open ends", has_dataset=True)
    assert coding.intent == "code_open_ends"


def test_chosen_cleaning_is_not_overwritten() -> None:
    """A route decision of clean_data is kept even when the words also say open ends."""
    contract = _contract(
        "code the open ends",
        "clean_data",
        "The user asked for a fraud check.",
        has_dataset=True,
    )
    assert contract.intent == "clean_data"
    assert contract.specialist == "cleaning"
    assert contract.defaults_used["route_reason"] == "The user asked for a fraud check."


def test_apply_without_a_recommendation_asks_first() -> None:
    """Applying removals without a saved recommendation does not drop anyone."""
    contract = _contract("apply the removals", has_dataset=True, has_cleaning=False)
    assert contract.intent == "apply_cleaning"
    assert contract.missing_required == ["cleaning_recommendation"]


async def test_route_instructions_name_cleaning(settings: Settings) -> None:
    """The route prompt offers the cleaning specialist."""

    async def _cleaning(*_args: object, **kwargs: object) -> RouteDecision:
        instructions = str(kwargs["instructions"])
        assert "clean_data" in instructions
        assert "apply_cleaning" in instructions
        assert "code_open_ends" in instructions
        return RouteDecision(intent="clean_data", reason="Fraud check.")

    with patch("app.agents.router.run_structured", _cleaning):
        decision = await choose_route(
            settings,
            text="recommend fraud respondents, including the open ends",
            snapshot=_snapshot(),
            session_id="route-1",
        )
    assert decision is not None and decision.intent == "clean_data"


def test_chosen_analysis_keeps_a_profile_follow_up() -> None:
    """A profile crosstab that the router kept on analysis still carries the prior request."""
    contract = _contract(
        "crosstab the segments by gender",
        "run_analysis",
        "The reply continues the segmentation.",
        has_dataset=True,
        has_tabspec=True,
        analysis_followup=True,
        prior_analysis_request="Run k-means clustering on the feature battery",
    )
    assert contract.intent == "run_analysis"
    assert "Follow-up instruction:" in contract.user_request
    assert "k-means" in contract.user_request
    assert contract.missing_required == []


def test_prolific_price_is_a_sample_purchase() -> None:
    """A Prolific price request does not wait on the route model."""
    contract = _contract("Price 400 UK adults on Prolific")
    assert contract.intent == "buy_sample"
    assert contract.specialist == "sample"
    assert contract.expected_outputs == ["sample_purchase"]


def test_study_brief_with_sample_still_drafts() -> None:
    """A pasted brief that mentions sample and Prolific still drafts a questionnaire."""
    contract = _contract("Audience: Adults 18+\nSample: 400 on Prolific\n")
    assert contract.intent == "create_questionnaire"


def test_decipher_program_is_not_a_sample_purchase() -> None:
    """Programming the survey stays on Decipher."""
    contract = _contract("Program the survey in Decipher")
    assert contract.intent == "program_decipher"


def test_price_acceptance_stays_on_the_sample() -> None:
    """Accepting a quoted price stays on the sample specialist."""
    accepted = _contract("the price looks good", sample_followup=True)
    assert accepted.intent == "buy_sample"
    draft = _contract("draft a questionnaire", sample_followup=True)
    assert draft.intent == "create_questionnaire"


def test_snapshot_includes_a_sample_purchase() -> None:
    """The route packet can see a sample quote and still omits artifact bodies."""
    snapshot = project_snapshot(
        artifact_versions_by_type={"sample_purchase": 2, "note": 1},
        dataset_active=False,
        variable_names=[],
        previous_reply="The quote is in the panel.",
        previous_intent="buy_sample",
        previous_status="completed",
        objectives=[],
    )
    assert snapshot["artifacts"] == {"sample_purchase": 2}
    assert "content" not in snapshot


async def test_route_keeps_a_sample_decision(settings: Settings) -> None:
    """A stubbed sample route wins when the words also mention a survey."""

    async def _sample(*_args: object, **kwargs: object) -> RouteDecision:
        instructions = str(kwargs["instructions"])
        assert "buy_sample" in instructions
        assert "study brief" in instructions
        return RouteDecision(intent="buy_sample", reason="Pricing a Prolific sample.")

    text = "Price 400 UK adults on Prolific and mention the survey"
    with patch("app.agents.router.run_structured", _sample):
        decision = await choose_route(
            settings, text=text, snapshot=_snapshot(), session_id="route-1"
        )
    assert decision is not None
    routed = _contract(text, decision.intent, decision.reason)
    assert routed.intent == "buy_sample"
    assert routed.specialist == "sample"
