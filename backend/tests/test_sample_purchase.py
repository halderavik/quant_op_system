"""Prolific quotes and launches, with the API mocked."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.engines.sample_audience import AudienceProposal, ProposedFilter
from app.errors import AppError
from app.main import create_app
from app.repositories.records import ArtifactRepository
from app.schemas.sample_purchase import SamplePurchase
from app.services.decipher_launch import LaunchResult
from app.services.prolific_client import ProlificClient
from app.services.sample_launch import launch_sample
from app.services.sample_quote import quote_from_message
from tests.conftest import create_project

_XML = """<?xml version="1.0" encoding="UTF-8"?>
<survey>
  <samplesources default="0">
    <samplesource list="0"><title>Open Survey</title></samplesource>
  </samplesources>
</survey>
"""
_FILTERS = {
    "results": [
        {
            "filter_id": "current-country-of-residence",
            "title": "Current country of residence",
            "type": "select",
            "choices": {"GB": "United Kingdom", "US": "United States"},
        },
        {"filter_id": "age", "title": "Age", "type": "range"},
        {
            "filter_id": "sex",
            "title": "Sex",
            "type": "select",
            "choices": {"0": "Male", "1": "Female"},
        },
    ]
}
_QUOTE = "Price 400 UK adults 18-65, half women, 10 minutes, on Prolific"


def _weighted_single_error(filters: list[dict]) -> dict:
    """Return the error Prolific sends for weighted filters on a SINGLE study.

    Args:
        filters: Filters that were sent.

    Returns:
        Error body keyed by the index of the weighted filter.
    """
    index = next(i for i, item in enumerate(filters) if "weightings" in item)
    message = (
        "You have created a filter with weightings, but have set the study type to SINGLE. "
        "Please either remove the weightings or set study type to QUOTA"
    )
    return {"error": {"detail": {str(index): {"non_field_errors": [message]}}}}


class _Api:
    """Records Prolific calls and returns fixture JSON."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.eligible = 12000
        self.balance = 500_000
        self.create_status = 201
        self.create_detail = "screen out payment is not available"
        self.ready = True
        self.breakdown: dict = {}
        self.created: dict = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        """Answer one mocked Prolific call.

        Args:
            request: Outgoing request.

        Returns:
            Fixture response.
        """
        path = request.url.path
        self.calls.append((request.method, path))
        if path.endswith("/filters/"):
            return httpx.Response(200, json=_FILTERS)
        if path.endswith("/eligibility-count/"):
            sent = json.loads(request.content)["filters"]
            if any("weightings" in item for item in sent):
                return httpx.Response(400, json=_weighted_single_error(sent))
            return httpx.Response(200, json={"count": self.eligible})
        if path.endswith("/reward-recommendations/"):
            return httpx.Response(
                200,
                json=[
                    {
                        "min_reward_per_hour": 1200,
                        "recommended_reward_per_hour": 800,
                        "currency": "GBP",
                    }
                ],
            )
        if path.endswith("/study-cost-calculator/"):
            body = json.loads(request.content)
            total = int(body["reward"]) * int(body["total_available_places"]) + 5000
            return httpx.Response(200, json={"total_cost": total})
        if path.endswith("/balance/"):
            return httpx.Response(
                200, json={"currency_code": "GBP", "available_balance": self.balance}
            )
        if path.endswith("/studies/") and request.method == "POST":
            self.created = json.loads(request.content)
            weighted = any("weightings" in item for item in self.created["filters"])
            if weighted and self.created.get("study_type", "SINGLE") == "SINGLE":
                return httpx.Response(400, json=_weighted_single_error(self.created["filters"]))
            if self.create_status != 201:
                return httpx.Response(self.create_status, json={"detail": self.create_detail})
            return httpx.Response(
                201,
                json={
                    "id": "study-1",
                    "status": "UNPUBLISHED",
                    "is_ready_to_publish": self.ready,
                    "minimum_reward_per_hour": 1200,
                },
            )
        if path.endswith("/cost/"):
            return httpx.Response(200, json=self.breakdown)
        if path.endswith("/transition/"):
            action = json.loads(request.content)["action"]
            status = {"PUBLISH": "ACTIVE", "PAUSE": "PAUSED", "STOP": "COMPLETED"}[action]
            return httpx.Response(200, json={"status": status})
        if path.endswith("/submissions/counts/"):
            return httpx.Response(200, json={"APPROVED": 3, "TOTAL": 3})
        if request.method == "GET" and "/studies/" in path:
            return httpx.Response(
                200,
                json={"id": "study-1", "status": "UNPUBLISHED", "is_ready_to_publish": self.ready},
            )
        return httpx.Response(404, json={"detail": path})


class _Launcher:
    """Captures the XML sent to Decipher."""

    def __init__(self) -> None:
        self.xml = ""
        self.calls = 0

    def launch(self, xml: str, name: str, survey_path: str | None = None) -> LaunchResult:
        """Record an upload.

        Args:
            xml: Survey document.
            name: Survey name.
            survey_path: Existing path.

        Returns:
            Successful upload of the same XML.
        """
        del name, survey_path
        self.calls += 1
        self.xml = xml
        return LaunchResult(
            launched=True,
            message="Uploaded.",
            survey_path="self/demo",
            survey_url="https://selfserve.decipherinc.com/survey/self/demo",
            xml=xml,
        )


def _settings(tmp_path: Path) -> Settings:
    """Return settings with a Prolific token that the mock never sends onward.

    Args:
        tmp_path: Temporary directory.

    Returns:
        Settings.
    """
    return Settings(
        openai_api_key="",
        database_url=f"sqlite:///{(tmp_path / 'studio.db').as_posix()}",
        storage_root=tmp_path / "storage",
        session_db_path=tmp_path / "sessions.db",
        run_tasks_inline=True,
        cors_origins="http://localhost:5173",
        prolific_api_key="prolific-secret",
        prolific_workspace_id="ws-1",
        prolific_project_id="proj-1",
        decipher_api_key="decipher-secret",
        decipher_api_base="https://selfserve.decipherinc.com/api/v1",
        decipher_company="self",
    )


def _client(settings: Settings) -> ProlificClient:
    """Build a client bound to a fresh mock.

    Args:
        settings: Settings.

    Returns:
        Client. The mock lives on ``client.api``.
    """
    api = _Api()
    client = ProlificClient(settings, transport=httpx.MockTransport(api.handler))
    client.api = api  # type: ignore[attr-defined]
    return client


async def test_quote_prices_the_audience_and_raises_the_reward(tmp_path: Path) -> None:
    """A UK quota quote uses the catalog, the minimum reward, and the calculator total."""
    settings = _settings(tmp_path)
    app = create_app(settings)
    prolific = _client(settings)
    with TestClient(app) as client:
        created = create_project(client)
    db = app.state.session_factory()
    try:
        outcome = await quote_from_message(db, settings, created["id"], _QUOTE, client=prolific)
        db.commit()
        saved = ArtifactRepository(db).latest_of_type(created["id"], "sample_purchase")
    finally:
        db.close()
    assert saved is not None
    purchase = SamplePurchase.model_validate(saved.content)
    assert purchase.sample_size == 400
    assert purchase.reward_cents == 200
    assert any("minimum" in warning.lower() for warning in purchase.warnings)
    assert purchase.total_cost_cents == 200 * 400 + 5000
    assert purchase.eligible_count == 12000
    assert purchase.currency == "GBP"
    assert purchase.status == "quoted"
    assert {item.filter_id for item in purchase.filters} == {
        "current-country-of-residence",
        "age",
        "sex",
    }
    assert sum(cell.places for cell in purchase.quota_cells) == 400
    assert outcome["summary"].startswith("Prolific quote")
    assert "not been published" in outcome["summary"]


async def test_unknown_filter_is_not_saved(tmp_path: Path) -> None:
    """A filter id outside the catalog rejects the quote."""
    settings = _settings(tmp_path)
    app = create_app(settings)
    prolific = _client(settings)
    with TestClient(app) as client:
        created = create_project(client)
    db = app.state.session_factory()
    proposal = AudienceProposal(
        filters=[ProposedFilter(filter_id="not-a-filter", selected_labels=["Left"])]
    )
    try:
        with pytest.raises(AppError) as caught:
            await quote_from_message(
                db,
                settings,
                created["id"],
                "Price 400 people, 10 minutes, on Prolific",
                client=prolific,
                proposal=proposal,
            )
        saved = ArtifactRepository(db).latest_of_type(created["id"], "sample_purchase")
    finally:
        db.close()
    assert "Unknown Prolific filter" in caught.value.message
    assert saved is None


async def test_representative_sample_does_not_add_age_filters(tmp_path: Path) -> None:
    """A US representative request sets the study type and no demographic filters."""
    settings = _settings(tmp_path)
    app = create_app(settings)
    prolific = _client(settings)
    with TestClient(app) as client:
        created = create_project(client)
    db = app.state.session_factory()
    try:
        await quote_from_message(
            db,
            settings,
            created["id"],
            "Price 200 US representative sample, 10 minutes",
            client=prolific,
        )
        saved = ArtifactRepository(db).latest_of_type(created["id"], "sample_purchase")
    finally:
        db.close()
    assert saved is not None
    purchase = SamplePurchase.model_validate(saved.content)
    assert purchase.study_type == "US_REP_SAMPLE"
    assert purchase.filters == []
    assert purchase.sample_size == 200


async def test_launch_publishes_only_the_confirmed_total(tmp_path: Path) -> None:
    """Publish sends the Decipher completion URLs and then the PUBLISH transition."""
    settings = _settings(tmp_path)
    app = create_app(settings)
    prolific = _client(settings)
    launcher = _Launcher()
    with TestClient(app) as client:
        created = create_project(client)
    db = app.state.session_factory()
    try:
        _store_survey(db, created["id"])
        await quote_from_message(db, settings, created["id"], _QUOTE, client=prolific)
        quoted = SamplePurchase.model_validate(
            ArtifactRepository(db).latest_of_type(created["id"], "sample_purchase").content
        )
        outcome = launch_sample(
            db,
            app.state.storage,
            settings,
            created["id"],
            quoted.total_cost_cents,
            client=prolific,
            launcher=launcher,
        )
        published = SamplePurchase.model_validate(
            ArtifactRepository(db).latest_of_type(created["id"], "sample_purchase").content
        )
    finally:
        db.close()
    assert outcome["launched"] is True
    assert prolific.api.created["study_type"] == "QUOTA"  # type: ignore[attr-defined]
    assert published.status == "active"
    assert published.prolific_study_id == "study-1"
    assert "https://app.prolific.com/submissions/complete?cc=" in launcher.xml
    assert 'list="1"' in launcher.xml
    assert "{{%PROLIFIC_PID%}}" in prolific.api.created["external_study_url"]  # type: ignore[attr-defined]
    assert ("POST", "/api/v1/studies/study-1/transition/") in prolific.api.calls  # type: ignore[attr-defined]


async def test_launch_refuses_a_changed_total_and_a_short_balance(tmp_path: Path) -> None:
    """A stale confirmation and a short balance do not publish."""
    settings = _settings(tmp_path)
    app = create_app(settings)
    prolific = _client(settings)
    launcher = _Launcher()
    with TestClient(app) as client:
        created = create_project(client)
    db = app.state.session_factory()
    try:
        _store_survey(db, created["id"])
        await quote_from_message(db, settings, created["id"], _QUOTE, client=prolific)
        changed = launch_sample(
            db,
            app.state.storage,
            settings,
            created["id"],
            1,
            client=prolific,
            launcher=launcher,
        )
        assert changed["launched"] is False
        assert launcher.calls == 0
        prolific.api.balance = 10  # type: ignore[attr-defined]
        await quote_from_message(db, settings, created["id"], _QUOTE, client=prolific)
        with pytest.raises(AppError) as caught:
            launch_sample(
                db,
                app.state.storage,
                settings,
                created["id"],
                200 * 400 + 5000,
                client=prolific,
                launcher=launcher,
            )
    finally:
        db.close()
    assert "balance" in caught.value.message.lower()
    assert not any(path.endswith("/transition/") for _method, path in prolific.api.calls)  # type: ignore[attr-defined]


async def test_zero_eligibility_blocks_launch(tmp_path: Path) -> None:
    """A count of zero is shown as fewer than five and is not published."""
    settings = _settings(tmp_path)
    app = create_app(settings)
    prolific = _client(settings)
    prolific.api.eligible = 0  # type: ignore[attr-defined]
    with TestClient(app) as client:
        created = create_project(client)
    db = app.state.session_factory()
    try:
        _store_survey(db, created["id"])
        await quote_from_message(db, settings, created["id"], _QUOTE, client=prolific)
        purchase = SamplePurchase.model_validate(
            ArtifactRepository(db).latest_of_type(created["id"], "sample_purchase").content
        )
        with pytest.raises(AppError) as caught:
            launch_sample(
                db,
                app.state.storage,
                settings,
                created["id"],
                purchase.total_cost_cents,
                client=prolific,
                launcher=_Launcher(),
            )
    finally:
        db.close()
    assert purchase.eligible_count == 0
    assert "fewer than 5" in purchase.eligible_note.lower()
    assert "fewer than 5" in caught.value.message.lower()


async def test_screenout_rejection_does_not_publish(tmp_path: Path) -> None:
    """A workspace that cannot pay screen-outs is left unpublished."""
    settings = _settings(tmp_path)
    app = create_app(settings)
    prolific = _client(settings)
    prolific.api.create_status = 422  # type: ignore[attr-defined]
    with TestClient(app) as client:
        created = create_project(client)
    db = app.state.session_factory()
    try:
        _store_survey(db, created["id"])
        await quote_from_message(db, settings, created["id"], _QUOTE, client=prolific)
        quoted = SamplePurchase.model_validate(
            ArtifactRepository(db).latest_of_type(created["id"], "sample_purchase").content
        )
        outcome = launch_sample(
            db,
            app.state.storage,
            settings,
            created["id"],
            quoted.total_cost_cents,
            client=prolific,
            launcher=_Launcher(),
        )
    finally:
        db.close()
    assert outcome["launched"] is False
    assert "screen-out" in outcome["summary"].lower()
    assert not any(path.endswith("/transition/") for _method, path in prolific.api.calls)  # type: ignore[attr-defined]


def test_launch_route_requires_confirmation(tmp_path: Path) -> None:
    """The panel cannot publish without confirm set."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        created = create_project(client)
        response = client.post(
            f"/api/projects/{created['id']}/sample/launch",
            json={"confirm": False, "total_cost_cents": 100},
        )
        health = client.get("/api/health")
    assert response.status_code == 400
    assert health.json()["prolific_configured"] is True
    assert "prolific-secret" not in health.text


async def test_missing_key_refuses_to_price(tmp_path: Path) -> None:
    """A blank token does not call Prolific."""
    settings = _settings(tmp_path)
    settings.prolific_api_key = ""
    app = create_app(settings)
    with TestClient(app) as client:
        created = create_project(client)
    db = app.state.session_factory()
    try:
        with pytest.raises(AppError) as caught:
            await quote_from_message(
                db, settings, created["id"], _QUOTE, client=ProlificClient(settings)
            )
    finally:
        db.close()
    assert caught.value.code == "prolific_not_configured"


def _store_survey(db, project_id: str) -> None:
    """Save a programmed survey the launch can redirect.

    Args:
        db: Session.
        project_id: Project id.
    """
    ArtifactRepository(db).create(
        project_id=project_id,
        artifact_type="decipher_survey",
        name="Decipher",
        content={
            "xml": _XML,
            "survey_url": "https://selfserve.decipherinc.com/survey/self/demo",
            "survey_path": "self/demo",
            "title": "Brand",
        },
        content_schema="decipher/1",
        created_by="test",
        validation_status="passed",
    )


def test_nested_prolific_error_reads_as_a_sentence() -> None:
    """A field error keyed by filter index is shown as its sentence, not as JSON."""
    from app.services.prolific_client import _detail

    body = _weighted_single_error([{"filter_id": "sex", "weightings": {"1": 0.5}}])
    text = _detail(body)
    assert text.startswith("You have created a filter with weightings")
    assert "{" not in text
