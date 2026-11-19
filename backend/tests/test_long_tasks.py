"""Long tasks: finished model answers are reused on a retry, and Cancel stops a running task."""

import asyncio
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.agents import sdk
from app.agents.orchestrator import Orchestrator
from app.config import Settings
from app.errors import AppError
from app.repositories.records import TaskRepository
from tests.conftest import create_project


class _Answer(BaseModel):
    value: str


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "openai_api_key": "sk-openai",
        "anthropic_api_key": "",
        "database_url": f"sqlite:///{(tmp_path / 'studio.db').as_posix()}",
        "storage_root": tmp_path / "storage",
        "session_db_path": tmp_path / "sessions.db",
        "cors_origins": "http://localhost:5173",
        "model_questionnaire": "gpt-6.1-sol",
    }
    values.update(overrides)
    return Settings(**values)


def test_a_finished_answer_is_reused_and_the_switch_turns_it_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second identical call reads the saved answer; with caching off it calls the model."""
    calls: list[str] = []

    async def _model(settings, model, name, instructions, prompt, output_type, session_id):
        calls.append(prompt)
        return _Answer(value=f"answer {len(calls)}")

    monkeypatch.setattr(sdk, "_run_model", _model)

    async def ask(settings: Settings, prompt: str = "read part 1") -> _Answer:
        return await sdk.run_structured(
            settings,
            name="t",
            instructions="Read.",
            prompt=prompt,
            output_type=_Answer,
            role="questionnaire",
            session_id="s",
            cache=True,
        )

    settings = _settings(tmp_path)
    first = asyncio.run(ask(settings))
    again = asyncio.run(ask(settings))
    assert first.value == again.value == "answer 1" and len(calls) == 1
    assert asyncio.run(ask(settings, "read part 2")).value == "answer 2"
    fresh = settings.model_copy(update={"model_call_cache": False})
    assert asyncio.run(ask(fresh)).value == "answer 3"


def test_cancel_stops_a_running_task_at_its_next_stage(client) -> None:
    """A task marked cancelled raises at its next progress message and ends as cancelled."""
    project = create_project(client)
    db = client.app.state.session_factory()
    try:
        task = TaskRepository(db).create(
            project["id"], project["conversation_id"], {"user_request": "x"}
        )
        task.status = "running"
        db.commit()
        other = client.app.state.session_factory()
        try:
            other_task = TaskRepository(other).get(task.id)
            other_task.status = "cancelled"
            other.commit()
        finally:
            other.close()
        orchestrator = Orchestrator(
            client.app.state.settings, client.app.state.session_factory, client.app.state.storage
        )
        with pytest.raises(AppError) as caught:
            orchestrator._event(db, task, "running", {"message": "Read 2 of 7 parts"})
        assert caught.value.code == "cancelled"
    finally:
        db.close()
