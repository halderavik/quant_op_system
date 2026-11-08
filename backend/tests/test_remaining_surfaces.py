"""Editors, codeframes, review, narrative guards, and the sandbox chart task."""

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.engines.codeframe_parse import parse_codeframe_bytes
from app.errors import AppError
from app.schemas.coding import Codeframe, CodeNode, NetNode
from app.services.codeframe_author import guard_codeframe
from tests.conftest import create_project

ROOT = Path(__file__).resolve().parents[2] / "fixtures"


def _questionnaire() -> dict:
    """Return a two-question instrument.

    Returns:
        Canonical questionnaire JSON.
    """
    return {
        "id": "q1",
        "title": "Brand trust",
        "objectives": [{"id": "o1", "description": "Trust", "question_ids": ["Q1", "Q2"]}],
        "modules": [
            {"id": "m1", "title": "Core", "question_ids": ["Q1"]},
            {"id": "m2", "title": "Follow up", "question_ids": ["Q2"]},
        ],
        "questions": [
            {
                "id": "Q1",
                "type": "single_select",
                "text": "First",
                "options": [{"code": 1, "label": "Yes"}],
            },
            {
                "id": "Q2",
                "type": "single_select",
                "text": "Second",
                "options": [{"code": 1, "label": "No"}],
            },
        ],
    }


def _create(
    client: TestClient, project_id: str, artifact_type: str, name: str, content: dict
) -> str:
    """Create an artifact and return its id.

    Args:
        client: Test client.
        project_id: Project id.
        artifact_type: Artifact type.
        name: Display name.
        content: Canonical JSON.

    Returns:
        Artifact id.
    """
    response = client.post(
        f"/api/projects/{project_id}/artifacts",
        json={"type": artifact_type, "name": name, "content": content},
    )
    assert response.status_code == 201, response.text
    return response.json()["artifact_id"]


def _latest(client: TestClient, project_id: str, artifact_id: str) -> dict:
    """Return the latest revision content for an artifact.

    Args:
        client: Test client.
        project_id: Project id.
        artifact_id: Artifact id.

    Returns:
        Latest revision payload.
    """
    artifacts = client.get(f"/api/projects/{project_id}/artifacts").json()
    match = next(item for item in artifacts if item["id"] == artifact_id)
    return match["latest"]


def test_reorder_survives_reload_and_a_stale_write_conflicts(client: TestClient) -> None:
    """Question order is stored, and a stale version is rejected."""
    project = create_project(client)
    document = _questionnaire()
    artifact_id = _create(client, project["id"], "questionnaire", "Instrument", document)
    document["questions"] = [document["questions"][1], document["questions"][0]]
    saved = client.post(
        f"/api/artifacts/{artifact_id}/revisions",
        json={"content": document, "expected_version": 1},
    )
    assert saved.status_code == 201, saved.text
    latest = _latest(client, project["id"], artifact_id)
    assert [item["id"] for item in latest["content"]["questions"]] == ["Q2", "Q1"]
    conflict = client.post(
        f"/api/artifacts/{artifact_id}/revisions",
        json={"content": document, "expected_version": 1},
    )
    assert conflict.status_code == 409


def test_deleting_the_last_question_fails_validation(client: TestClient) -> None:
    """An empty instrument is saved and flagged."""
    project = create_project(client)
    document = _questionnaire()
    artifact_id = _create(client, project["id"], "questionnaire", "Instrument", document)
    document["questions"] = []
    document["objectives"] = []
    document["modules"] = []
    saved = client.post(
        f"/api/artifacts/{artifact_id}/revisions",
        json={"content": document, "expected_version": 1},
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["validation_status"] == "failed"
    assert any(
        issue["code"] == "empty_instrument" for issue in saved.json()["validation"]["issues"]
    )


def test_copied_table_round_trips_and_duplicate_ids_are_rejected(client: TestClient) -> None:
    """A new table id is stored, and a repeated id is not."""
    project = create_project(client)
    spec = {
        "spec_id": "s1",
        "banners": [{"id": "b1", "label": "Gender", "categories": []}],
        "tables": [{"id": "T1", "title": "Trust", "banner_ids": ["b1"]}],
    }
    artifact_id = _create(client, project["id"], "tabspec", "Spec", spec)
    spec["tables"] = [
        spec["tables"][0],
        {"id": "T2", "title": "Trust copy", "banner_ids": ["b1"]},
    ]
    saved = client.post(
        f"/api/artifacts/{artifact_id}/revisions",
        json={"content": spec, "expected_version": 1},
    )
    assert saved.status_code == 201, saved.text
    latest = _latest(client, project["id"], artifact_id)
    assert [table["id"] for table in latest["content"]["tables"]] == ["T1", "T2"]
    spec["tables"][1]["id"] = "T1"
    rejected = client.post(
        f"/api/artifacts/{artifact_id}/revisions",
        json={"content": spec, "expected_version": 2},
    )
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "duplicate_table"
    spec["tables"][1]["id"] = "T3"
    spec["tables"][1]["banner_ids"] = ["missing"]
    missing = client.post(
        f"/api/artifacts/{artifact_id}/revisions",
        json={"content": spec, "expected_version": 2},
    )
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "bad_banner"


def _analysis() -> dict:
    """Return a report whose one claim matches the result.

    Returns:
        Analysis artifact content.
    """
    return {
        "result": {
            "method": "descriptive",
            "sample_flow": {"valid_n": 10},
            "metrics": {},
            "model_estimates": {},
            "diagnostics": {"note": "ok"},
            "warnings": [],
            "script": "print(10)\n",
        },
        "report": {
            "title": "Descriptive",
            "method": "descriptive",
            "sections": [{"id": "findings", "narrative": "Sample text without a new figure."}],
            "claims": [
                {
                    "path": "sample_flow.valid_n",
                    "stated_value": 10,
                    "sentence": "The analysis sample is 10 complete respondents.",
                }
            ],
            "rendered": "The analysis sample is 10 complete respondents.",
            "caveats": ["Associations are sample estimates."],
        },
    }


def test_caveat_edit_creates_a_revision_and_a_forged_claim_is_rejected(client: TestClient) -> None:
    """Prose caveats save. A claim that disagrees with the result does not."""
    project = create_project(client)
    content = _analysis()
    artifact_id = _create(client, project["id"], "analysis", "Descriptive", content)
    content["report"]["caveats"] = ["Edited caveat without digits."]
    saved = client.post(
        f"/api/artifacts/{artifact_id}/revisions",
        json={"content": content, "expected_version": 1},
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["version"] == 2
    assert saved.json()["content"]["report"]["rendered"].startswith("The analysis sample is 10")
    content["report"]["claims"][0]["stated_value"] = 11
    forged = client.post(
        f"/api/artifacts/{artifact_id}/revisions",
        json={"content": content, "expected_version": 2},
    )
    assert forged.status_code == 400
    content["report"]["claims"][0]["stated_value"] = 10
    content["report"]["sections"][0]["narrative"] = "The lift is 99."
    prose = client.post(
        f"/api/artifacts/{artifact_id}/revisions",
        json={"content": content, "expected_version": 2},
    )
    assert prose.status_code == 400
    assert prose.json()["error"]["code"] == "unclaimed_number"


def test_codeframe_csv_matches_the_contract_and_extra_columns_are_flagged() -> None:
    """The sample contract row shape parses, and an unknown column is listed."""
    csv_text = (
        "id,label,parent_id,definition,include_examples,exclude_examples,child_ids\n"
        "C01,Product quality,N01,Comments about quality of product,Reliable materials,Store service,\n"
        "C02,Service,N01,Service experience,,,\n"
        "N01,Product/service positives,,,,,C01|C02\n"
    )
    parsed = parse_codeframe_bytes("codeframe.csv", csv_text.encode("utf-8"))
    assert parsed.codeframe.codes[0].id == "C01"
    assert parsed.codeframe.codes[0].include_examples == ["Reliable materials"]
    assert parsed.codeframe.codes[0].exclude_examples == ["Store service"]
    assert parsed.codeframe.nets[0].child_ids == ["C01", "C02"]
    extra = csv_text.replace("child_ids", "child_ids,notes")
    extra = extra.replace("C01|C02", "C01|C02,ignore me")
    flagged = parse_codeframe_bytes("codeframe.csv", extra.encode("utf-8"))
    assert flagged.ignored_columns == ["notes"]
    book = Workbook()
    sheet = book.active
    sheet.append(["id", "label", "notes"])
    sheet.append(["C01", "Quality", "extra"])
    buffer = io.BytesIO()
    book.save(buffer)
    xlsx = parse_codeframe_bytes("codeframe.xlsx", buffer.getvalue())
    assert xlsx.ignored_columns == ["notes"]
    assert xlsx.codeframe.codes[0].label == "Quality"


def test_duplicate_proposed_code_id_fails() -> None:
    """A proposal with the same code id twice is rejected."""
    frame = Codeframe(
        codeframe_id="cf",
        response_variable="comment",
        respondent_id_variable="respondent_id",
        codes=[CodeNode(id="C01", label="A"), CodeNode(id="C01", label="B")],
    )
    with pytest.raises(AppError) as caught:
        guard_codeframe(frame)
    assert caught.value.code == "duplicate_code"


def test_codeframe_example_edit_bumps_the_version(client: TestClient) -> None:
    """Editing an include example stores a new codeframe version."""
    project = create_project(client)
    frame = Codeframe(
        codeframe_id="cf",
        response_variable="comment",
        respondent_id_variable="respondent_id",
        codes=[CodeNode(id="C01", label="Quality", include_examples=["Reliable"])],
        nets=[NetNode(id="N01", label="Any", child_ids=["C01"])],
    )
    artifact_id = _create(
        client, project["id"], "codeframe", "Comments", frame.model_dump(mode="json")
    )
    content = frame.model_dump(mode="json")
    content["codes"][0]["include_examples"] = ["Reliable", "Well made"]
    saved = client.post(
        f"/api/artifacts/{artifact_id}/revisions",
        json={"content": content, "expected_version": 1},
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["content"]["version"] == 2
    assert saved.json()["content"]["codes"][0]["include_examples"] == ["Reliable", "Well made"]


def test_review_override_recomputes_and_reload_keeps_it(client: TestClient) -> None:
    """One reviewer change updates the code count, keeps the net deduplicated, and reloads."""
    project = create_project(client)
    frame = Codeframe(
        codeframe_id="cf",
        response_variable="comment",
        respondent_id_variable="respondent_id",
        codes=[CodeNode(id="C01", label="Quality"), CodeNode(id="C02", label="Service")],
        nets=[NetNode(id="N01", label="Any", child_ids=["C01", "C02"])],
    )
    _create(client, project["id"], "codeframe", "Comments", frame.model_dump(mode="json"))
    coding = {
        "codeframe_id": "cf",
        "assignments": [
            {
                "respondent_id": "1",
                "source_row_id": 1,
                "response_text": "Good quality but slow service",
                "assigned_code_ids": ["C01", "C02"],
                "sentiment": "mixed",
                "substantive": True,
            },
            {
                "respondent_id": "2",
                "source_row_id": 2,
                "response_text": "n/a",
                "assigned_code_ids": ["C01"],
                "sentiment": "unclear",
                "substantive": True,
            },
        ],
        "report": {},
    }
    artifact_id = _create(client, project["id"], "coding", "Coding", coding)
    coding["assignments"][0]["human_overrides"] = {"code_ids": ["C02"], "sentiment": "negative"}
    saved = client.post(
        f"/api/artifacts/{artifact_id}/revisions",
        json={"content": coding, "expected_version": 1},
    )
    assert saved.status_code == 201, saved.text
    report = saved.json()["content"]["report"]
    counts = {item["id"]: item["unweighted_respondents"] for item in report["frequencies"]}
    assert counts["C01"] == 0
    assert counts["C02"] == 1
    assert counts["N01"] == 1
    assert report["substantive_n"] == 1
    assert report["nonsubstantive_n"] == 1
    reloaded = _latest(client, project["id"], artifact_id)
    assert reloaded["content"]["assignments"][0]["human_overrides"]["code_ids"] == ["C02"]
    coding["assignments"][0]["human_overrides"] = {"code_ids": ["C99"], "sentiment": "negative"}
    rejected = client.post(
        f"/api/artifacts/{artifact_id}/revisions",
        json={"content": coding, "expected_version": 2},
    )
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "invalid_code"


def test_propose_and_import_do_not_code_rows(client: TestClient) -> None:
    """A proposal and an import store a codeframe and leave coding unstarted."""
    project = create_project(client)
    sav = ROOT / "survey_small.sav"
    with sav.open("rb") as handle:
        uploaded = client.post(
            f"/api/projects/{project['id']}/files",
            files={"file": ("survey_small.sav", handle, "application/octet-stream")},
        )
    assert uploaded.status_code == 201, uploaded.text
    proposed = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={
            "content": "propose a codeframe for column comment using respondent id respondent_id"
        },
    )
    assert proposed.status_code == 201, proposed.text
    task = client.get(f"/api/tasks/{proposed.json()['task_id']}").json()
    assert task["status"] == "completed_with_warnings", task
    csv_text = (
        "id,label,parent_id,definition,include_examples,exclude_examples,child_ids\n"
        "C01,Product quality,N01,Quality,Reliable materials,Store service,\n"
        "N01,Positives,,,,,C01\n"
    )
    imported_file = client.post(
        f"/api/projects/{project['id']}/files",
        files={"file": ("codeframe.csv", csv_text.encode("utf-8"), "text/csv")},
    )
    assert imported_file.status_code == 201, imported_file.text
    imported = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": "import this codeframe"},
    )
    task = client.get(f"/api/tasks/{imported.json()['task_id']}").json()
    assert task["status"] == "completed_with_warnings", task
    artifacts = client.get(f"/api/projects/{project['id']}/artifacts").json()
    assert "coding" not in {item["type"] for item in artifacts}
    frame = next(item for item in artifacts if item["type"] == "codeframe")
    assert frame["latest"]["validation_status"] == "needs_review"
    assert any(code["id"] == "C01" for code in frame["latest"]["content"]["codes"])


def test_chart_request_records_one_job_and_a_file(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A chart from the latest table records a job, and traces stay off by default."""
    monkeypatch.setattr("app.sandbox.runner.docker_available", lambda: False)
    project = create_project(client)
    with (ROOT / "survey_small.sav").open("rb") as handle:
        client.post(
            f"/api/projects/{project['id']}/files",
            files={"file": ("survey_small.sav", handle, "application/octet-stream")},
        )
    table = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": "trust by gender weighted using weight"},
    )
    assert client.get(f"/api/tasks/{table.json()['task_id']}").json()["status"] in {
        "completed",
        "completed_with_warnings",
    }
    prompt = "Make a chart from the latest table and put it in a short report."
    chart = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": prompt},
    )
    task = client.get(f"/api/tasks/{chart.json()['task_id']}").json()
    assert task["status"] == "completed", task
    jobs = client.get(f"/api/projects/{project['id']}/jobs").json()
    assert len(jobs) == 1
    assert jobs[0]["status"] == "completed"
    assert "prompt" not in jobs[0]["manifest"]
    log = client.app.state.storage.read_bytes(project["id"], jobs[0]["log_relpath"]).decode("utf-8")
    assert prompt not in log
    artifacts = client.get(f"/api/projects/{project['id']}/artifacts").json()
    chart_artifact = next(item for item in artifacts if item["type"] == "chart")
    warning = chart_artifact["latest"]["content"]["provenance"]["warning"]
    assert "not a secure sandbox" in warning
    file_id = chart_artifact["latest"]["content"]["chart_file_id"]
    downloaded = client.get(f"/api/files/{file_id}/download")
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"<svg")
    assert b"source estimate" in chart_artifact["latest"]["content"]["rendered"].encode(
        "utf-8"
    ) or ("source estimate" in chart_artifact["latest"]["content"]["rendered"])
    traced = client.patch(
        f"/api/projects/{project['id']}",
        json={"study_context": {"store_traces": True}},
    )
    assert traced.status_code == 200
    again = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": prompt},
    )
    assert client.get(f"/api/tasks/{again.json()['task_id']}").json()["status"] == "completed"
    jobs = client.get(f"/api/projects/{project['id']}/jobs").json()
    assert len(jobs) == 2
    assert jobs[-1]["manifest"]["prompt"] == prompt
    assert json.dumps(jobs[0]["manifest"]).find(prompt) == -1
