"""Shared API client pointed at a temporary SQLite database."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Build isolated settings.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        Settings with inline tasks and no API key.
    """
    return Settings(
        openai_api_key="",
        database_url=f"sqlite:///{(tmp_path / 'studio.db').as_posix()}",
        storage_root=tmp_path / "storage",
        session_db_path=tmp_path / "sessions.db",
        run_tasks_inline=True,
        max_upload_mb=5,
        cors_origins="http://localhost:5173",
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    """Return a test client.

    Args:
        settings: Isolated settings.

    Returns:
        Test client.
    """
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def create_project(client: TestClient, name: str = "Brand Trust") -> dict:
    """Create a project and return the JSON body.

    Args:
        client: Test client.
        name: Project name.

    Returns:
        Response JSON.
    """
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()
