"""Questionnaire drafts must not hold the SQLite write lock during the model call."""

import asyncio
import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.agents.orchestrator import Orchestrator
from app.config import Settings
from app.db.session import make_engine
from app.main import create_app
from app.repositories.records import ArtifactRepository, ProjectRepository, TaskRepository
from app.schemas.questionnaire import Module, Objective, Option, Question, Questionnaire
from tests.conftest import create_project


def _instrument() -> Questionnaire:
    """Return a one-question instrument the fake model can save.

    Returns:
        Questionnaire.
    """
    return Questionnaire(
        id="q1",
        title="Coffee buyer survey",
        objectives=[Objective(id="o1", description="Measure purchase", question_ids=["Q1"])],
        modules=[Module(id="m1", title="Core", question_ids=["Q1"])],
        questions=[
            Question(
                id="Q1",
                type="single_select",
                text="How often do you buy coffee for home?",
                options=[Option(code=1, label="Weekly"), Option(code=2, label="Monthly")],
            )
        ],
    )


def test_sqlite_busy_timeout_is_explicit(settings: Settings) -> None:
    """Each connection waits a known interval instead of failing at once."""
    engine = make_engine(settings)
    with engine.connect() as connection:
        timeout = connection.exec_driver_sql("PRAGMA busy_timeout").scalar()
    assert timeout == 8000


async def test_draft_allows_another_message_to_save(settings: Settings) -> None:
    """A second chat write commits while the questionnaire model call is still waiting."""
    app = create_app(settings)
    started = asyncio.Event()
    release = asyncio.Event()

    async def wait_for_release(*_args: object, **_kwargs: object) -> Questionnaire:
        started.set()
        await release.wait()
        return _instrument()

    with TestClient(app) as client:
        project = create_project(client, "Northstar")
        db = app.state.session_factory()
        task = TaskRepository(db).create(
            project["id"],
            project["conversation_id"],
            {"user_request": "Write a questionnaire. Audience: coffee buyers. Sample: 600."},
        )
        db.commit()
        task_id = task.id
        db.close()
        orchestrator = Orchestrator(settings, app.state.session_factory, app.state.storage)
        with patch("app.agents.orchestrator.run_structured", wait_for_release):
            running = asyncio.create_task(orchestrator.run(task_id))
            await asyncio.wait_for(started.wait(), timeout=5)
            other = app.state.session_factory()
            began = time.perf_counter()
            try:
                ProjectRepository(other).add_message(
                    project["conversation_id"], "user", "please keep drafting"
                )
                other.commit()
            finally:
                other.close()
            assert time.perf_counter() - began < 2
            release.set()
            await asyncio.wait_for(running, timeout=5)
        check = app.state.session_factory()
        try:
            status = TaskRepository(check).get(task_id).status
            artifacts = ArtifactRepository(check).list_project(project["id"])
        finally:
            check.close()
    assert status in {"completed", "completed_with_warnings"}
    assert any(row.type == "questionnaire" for row in artifacts)


async def test_cancelled_task_does_not_call_the_model(settings: Settings) -> None:
    """A cancel recorded before the run starts skips drafting."""
    app = create_app(settings)
    called = False

    async def fail_if_called(*_args: object, **_kwargs: object) -> Questionnaire:
        nonlocal called
        called = True
        return _instrument()

    with TestClient(app) as client:
        project = create_project(client, "Paused")
        db = app.state.session_factory()
        task = TaskRepository(db).create(
            project["id"],
            project["conversation_id"],
            {"user_request": "Write a questionnaire for coffee buyers."},
        )
        task.status = "cancelled"
        db.commit()
        task_id = task.id
        db.close()
        orchestrator = Orchestrator(settings, app.state.session_factory, app.state.storage)
        with patch("app.agents.orchestrator.run_structured", fail_if_called):
            await orchestrator.run(task_id)
        check = app.state.session_factory()
        try:
            status = TaskRepository(check).get(task_id).status
        finally:
            check.close()
    assert called is False
    assert status == "cancelled"


async def test_unexpected_draft_error_is_marked_failed(settings: Settings) -> None:
    """A model crash is stored as a failed task instead of staying running."""
    app = create_app(settings)

    async def explode(*_args: object, **_kwargs: object) -> Questionnaire:
        raise RuntimeError("model socket closed")

    with TestClient(app) as client:
        project = create_project(client, "Broken draft")
        db = app.state.session_factory()
        task = TaskRepository(db).create(
            project["id"],
            project["conversation_id"],
            {"user_request": "Write a questionnaire. Audience: adults. Sample: 600."},
        )
        db.commit()
        task_id = task.id
        db.close()
        orchestrator = Orchestrator(settings, app.state.session_factory, app.state.storage)
        with patch("app.agents.orchestrator.run_structured", explode):
            await orchestrator.run(task_id)
        check = app.state.session_factory()
        try:
            row = TaskRepository(check).get(task_id)
            messages = ProjectRepository(check).messages(project["conversation_id"])
        finally:
            check.close()
    assert row.status == "failed"
    assert "RuntimeError" in (row.error or "")
    assert any("RuntimeError" in message.content for message in messages)
