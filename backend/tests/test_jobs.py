"""Job rows for sandbox runs: one row, timeout, cancel, and a hidden API key."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.jobs import execute_job
from tests.conftest import create_project


@pytest.fixture(autouse=True)
def _subprocess_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep these tests on the labelled fallback so they do not pull an image."""
    monkeypatch.setattr("app.sandbox.runner.docker_available", lambda: False)


def test_successful_run_writes_one_row_and_hides_the_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A finished script is one job, and the child environment has no API key."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak")
    project = create_project(client)
    db = client.app.state.session_factory()
    try:
        job = execute_job(
            db,
            client.app.state.storage,
            client.app.state.settings,
            project["id"],
            kind="sandbox",
            script=(
                "import os\n"
                "print('KEY=' + str(os.environ.get('OPENAI_API_KEY')))\n"
                "print('ANTHROPIC=' + str(os.environ.get('ANTHROPIC_API_KEY')))\n"
            ),
        )
        db.commit()
        job_id = job.id
    finally:
        db.close()
    listed = client.get(f"/api/projects/{project['id']}/jobs")
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["id"] == job_id
    assert rows[0]["status"] == "completed"
    assert rows[0]["manifest"]["memory_mb"] == client.app.state.settings.sandbox_memory_mb
    assert (
        rows[0]["manifest"]["timeout_seconds"] == client.app.state.settings.sandbox_timeout_seconds
    )
    stdout = rows[0]["manifest"].get("stdout", "")
    assert "sk-should-not-leak" not in stdout
    assert "sk-ant-should-not-leak" not in stdout
    log = client.app.state.storage.read_bytes(project["id"], rows[0]["log_relpath"]).decode("utf-8")
    assert "sk-should-not-leak" not in log
    assert "sk-ant-should-not-leak" not in log
    assert "prompt" not in rows[0]["manifest"]


def test_timeout_is_failed_and_writes_a_log(client: TestClient) -> None:
    """A script that outlives the cap is failed and still has a log file."""
    project = create_project(client)
    client.app.state.settings.sandbox_timeout_seconds = 1
    db = client.app.state.session_factory()
    try:
        job = execute_job(
            db,
            client.app.state.storage,
            client.app.state.settings,
            project["id"],
            kind="sandbox",
            script="import time\ntime.sleep(30)\n",
        )
        db.commit()
        relative = job.log_relpath
        status = job.status
    finally:
        db.close()
    assert status == "failed"
    assert relative
    assert client.app.state.storage.resolve(project["id"], relative).exists()


def test_cancel_does_not_insert_a_second_row(client: TestClient) -> None:
    """Cancelling twice returns the original job."""
    project = create_project(client)
    db = client.app.state.session_factory()
    try:
        job = execute_job(
            db,
            client.app.state.storage,
            client.app.state.settings,
            project["id"],
            kind="sandbox",
            script="print('ok')\n",
        )
        db.commit()
        job_id = job.id
    finally:
        db.close()
    first = client.post(f"/api/jobs/{job_id}/cancel")
    second = client.post(f"/api/jobs/{job_id}/cancel")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"] == job_id
    listed = client.get(f"/api/projects/{project['id']}/jobs").json()
    assert len(listed) == 1


def test_escape_from_the_job_directory_fails(client: TestClient, tmp_path: Path) -> None:
    """A script that reads outside the job directory does not complete."""
    project = create_project(client)
    secret = tmp_path / "secret.txt"
    secret.write_text("hidden", encoding="utf-8")
    db = client.app.state.session_factory()
    try:
        job = execute_job(
            db,
            client.app.state.storage,
            client.app.state.settings,
            project["id"],
            kind="sandbox",
            script=f"open(r'{secret}', 'r').read()\n",
        )
        db.commit()
        status = job.status
    finally:
        db.close()
    assert status == "failed"
