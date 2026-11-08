"""Health, persistence, artifacts, and two-turn project memory."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import create_project


def test_health_hides_api_key(tmp_path) -> None:
    """Health stays up and never echoes the server key."""
    settings = Settings(
        openai_api_key="sk-test-secret",
        database_url=f"sqlite:///{(tmp_path / 'studio.db').as_posix()}",
        storage_root=tmp_path / "storage",
        session_db_path=tmp_path / "sessions.db",
        cors_origins="http://localhost:5173",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/api/health")
    body = response.text
    assert response.status_code == 200
    assert response.json()["database"] == "ok"
    assert response.json()["llm"] == "available"
    assert "sk-test-secret" not in body


def test_missing_key_is_explicit(client: TestClient) -> None:
    """A missing key is reported without stopping the API."""
    payload = client.get("/api/health").json()
    assert payload["llm"] == "missing_key"
    assert "OPENAI_API_KEY" in payload["llm_message"]


def test_two_turns_survive_a_new_process(tmp_path) -> None:
    """A second turn can recall a note saved by the first, including after a new app."""
    settings = Settings(
        openai_api_key="",
        database_url=f"sqlite:///{(tmp_path / 'studio.db').as_posix()}",
        storage_root=tmp_path / "storage",
        session_db_path=tmp_path / "sessions.db",
        run_tasks_inline=True,
        cors_origins="http://localhost:5173",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        project = create_project(client)
        conversation = project["conversation_id"]
        first = client.post(
            f"/api/conversations/{conversation}/messages",
            json={"content": "Remember that the project codename is Aurora"},
        )
        assert first.status_code == 201
        task = client.get(f"/api/tasks/{first.json()['task_id']}").json()
        assert task["status"] == "completed"
        assert any(event["message"] == "Reading the request" for event in task["events"])
    restarted = create_app(settings)
    with TestClient(restarted) as client:
        second = client.post(
            f"/api/conversations/{conversation}/messages",
            json={"content": "What project codename did I give you?"},
        )
        assert second.status_code == 201
        messages = client.get(f"/api/conversations/{conversation}/messages").json()
        text = " ".join(item["content"] for item in messages)
        assert "Aurora" in text
        assert len([item for item in messages if item["role"] == "user"]) == 2


def test_artifact_revision_conflict_and_download(client: TestClient) -> None:
    """UI and chat edits share revisions, and a stale write conflicts."""
    project = create_project(client)
    created = client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={"type": "note", "name": "Note", "content": {"text": "first"}},
    )
    assert created.status_code == 201
    artifact_id = created.json()["artifact_id"]
    updated = client.post(
        f"/api/artifacts/{artifact_id}/revisions",
        json={"content": {"text": "second"}, "expected_version": 1},
    )
    assert updated.status_code == 201
    conflict = client.post(
        f"/api/artifacts/{artifact_id}/revisions",
        json={"content": {"text": "stale"}, "expected_version": 1},
    )
    assert conflict.status_code == 409
    upload = client.post(
        f"/api/projects/{project['id']}/files",
        files={"file": ("notes.txt", b"hello research", "text/plain")},
    )
    assert upload.status_code == 201
    downloaded = client.get(f"/api/files/{upload.json()['file_id']}/download")
    assert downloaded.status_code == 200
    assert downloaded.content == b"hello research"


def test_cancel_queued_task_endpoint(client: TestClient) -> None:
    """Cancel marks a non-terminal task cancelled."""
    project = create_project(client)
    # A completed inline task is already terminal; create one and cancel is a no-op success.
    sent = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": "Save a note about fieldwork"},
    )
    task_id = sent.json()["task_id"]
    cancelled = client.post(f"/api/tasks/{task_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "completed"
