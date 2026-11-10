"""Chat runs the saved tab spec instead of asking for one row and one banner."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.errors import AppError
from app.repositories.records import ArtifactRepository
from app.schemas.tabspec import Banner, BannerCategory, StudyDefaults, TableSpec, TabSpec
from app.services.tabspec_run import run_saved_tabspec
from tests.conftest import create_project

ROOT_SAV = Path(__file__).resolve().parents[2] / "fixtures" / "survey_small.sav"


def _trust_table(**kwargs: object) -> TableSpec:
    """Return the trust-by-gender table.

    Args:
        **kwargs: TableSpec overrides.

    Returns:
        Table spec.
    """
    payload = dict(
        id="T001",
        title="Trust by gender",
        row_variable_names=["trust"],
        banner_ids=["bn1"],
        weight_variable="weight",
    )
    payload.update(kwargs)
    return TableSpec(**payload)


def _spec(*tables: TableSpec) -> TabSpec:
    """Return a one-banner spec.

    Args:
        *tables: Table rows. Defaults to trust by gender.

    Returns:
        Tab spec.
    """
    return TabSpec(
        spec_id="saved-spec",
        study_defaults=StudyDefaults(weight_variable="weight"),
        banners=[
            Banner(
                id="bn1",
                label="Gender",
                variable_name="gender",
                categories=[
                    BannerCategory(label="Male", codes=[1]),
                    BannerCategory(label="Female", codes=[2]),
                ],
            )
        ],
        tables=list(tables) or [_trust_table()],
    )


def _upload_survey(client: TestClient, project_id: str) -> None:
    """Select the small SPSS fixture as the active dataset.

    Args:
        client: Test client.
        project_id: Project id.
    """
    with ROOT_SAV.open("rb") as handle:
        uploaded = client.post(
            f"/api/projects/{project_id}/files",
            files={"file": ("survey_small.sav", handle, "application/octet-stream")},
        )
    assert uploaded.status_code == 201, uploaded.text


def _save_spec(client: TestClient, project_id: str, spec: TabSpec, **extra: object) -> str:
    """Store a tab spec, including keys the panel keeps beside the schema.

    Args:
        client: Test client.
        project_id: Project id.
        spec: Tab spec.
        **extra: Extra content keys, such as an export id.

    Returns:
        Artifact id.
    """
    saved = client.post(
        f"/api/projects/{project_id}/artifacts",
        json={
            "type": "tabspec",
            "name": "Tab specification",
            "content": {**spec.model_dump(mode="json"), **extra},
            "content_schema": "tabspec/1",
        },
    )
    assert saved.status_code == 201, saved.text
    return saved.json()["artifact_id"]


def test_saved_spec_runs_and_stores_the_book(client: TestClient) -> None:
    """The latest spec supplies the row and banner, and the book is downloadable."""
    project = create_project(client)
    _upload_survey(client, project["id"])
    spec_id = _save_spec(client, project["id"], _spec(), export_file_id="ignored-export")
    db = client.app.state.session_factory()
    try:
        outcome = run_saved_tabspec(db, client.app.state.storage, project["id"])
        stored = ArtifactRepository(db).latest(outcome["artifact_id"])
        assert stored is not None
        assert stored.derived_from == [{"type": "tabspec", "id": spec_id, "version": 1}]
        db.commit()
    finally:
        db.close()
    assert outcome["status"] == "completed"
    assert outcome["summary"] == (
        "Ran 1 table from tab spec version 1. 0 tables were recorded as exceptions. "
        "The workbook is in the panel."
    )
    artifacts = client.get(f"/api/projects/{project['id']}/artifacts").json()
    book = next(item for item in artifacts if item["type"] == "crosstab")
    content = book["latest"]["content"]
    assert content["tables"][0]["table_id"] == "T001"
    assert "rows" not in content["tables"][0]
    assert content["exceptions"] == []
    grid = client.get(f"/api/artifacts/{book['id']}/tables/T001")
    assert grid.status_code == 200, grid.text
    assert grid.json()["rows"]
    assert grid.json()["columns"][0]["label"] == "Male"
    download = client.get(f"/api/files/{content['export_file_id']}/download")
    assert download.status_code == 200
    assert download.content[:2] == b"PK"


def test_open_end_is_held_while_the_closed_table_runs(client: TestClient) -> None:
    """An open end stays an exception. The closed table from the same spec still runs."""
    project = create_project(client)
    _upload_survey(client, project["id"])
    spec = _spec(
        _trust_table(id="Topen", title="Comment", plan_type="Open end", row_variable_names=["Qoe"]),
        _trust_table(),
    )
    _save_spec(client, project["id"], spec, export_file_id="ignored-export")
    db = client.app.state.session_factory()
    try:
        outcome = run_saved_tabspec(db, client.app.state.storage, project["id"])
        db.commit()
    finally:
        db.close()
    assert outcome["status"] == "completed_with_warnings"
    assert "Ran 1 table from tab spec version 1." in outcome["summary"]
    assert outcome["warnings"][0].startswith("Open end")


def test_missing_spec_names_the_next_step(client: TestClient) -> None:
    """A cross-tab request with no spec does not ask for row_variable."""
    project = create_project(client)
    db = client.app.state.session_factory()
    try:
        with pytest.raises(AppError) as caught:
            run_saved_tabspec(db, client.app.state.storage, project["id"])
    finally:
        db.close()
    assert caught.value.code == "missing_tabspec"
    assert "row_variable" not in caught.value.message
    assert "saved tab spec" in caught.value.message
    response = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": "generate cross-tabs based on the specs"},
    )
    task = client.get(f"/api/tasks/{response.json()['task_id']}").json()
    assert task["status"] == "clarification_needed"
    assert "row_variable" not in task["error"]
    assert "saved tab spec" in task["error"]


def test_saved_spec_without_a_dataset_asks_for_an_upload(client: TestClient) -> None:
    """A saved spec still needs the active SPSS file, and does not ask for a banner name."""
    project = create_project(client)
    _save_spec(client, project["id"], _spec())
    response = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": "generate cross-tabs based on the specs"},
    )
    task = client.get(f"/api/tasks/{response.json()['task_id']}").json()
    assert task["status"] == "clarification_needed"
    assert task["error"] == "Upload an SPSS file before running this. I will not invent a dataset."
    assert "row_variable" not in task["error"]


def test_chat_runs_cross_tabs_from_the_saved_spec(client: TestClient) -> None:
    """The same wording that used to ask for variables now runs the saved spec."""
    project = create_project(client)
    _upload_survey(client, project["id"])
    _save_spec(client, project["id"], _spec())
    response = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": "generate cross-tabs based on the specs"},
    )
    assert response.status_code == 201, response.text
    task = client.get(f"/api/tasks/{response.json()['task_id']}").json()
    assert task["status"] == "completed"
    messages = client.get(f"/api/conversations/{project['conversation_id']}/messages").json()
    reply = messages[-1]["content"]
    assert "Ran 1 table from tab spec version 1." in reply
    assert "row_variable" not in reply
    assert "banner_variable" not in reply
