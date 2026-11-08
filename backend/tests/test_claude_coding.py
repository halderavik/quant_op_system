"""Coding roles call Claude. OpenAI probe does not treat those ids as missing."""

import sys
import types
from pathlib import Path

import pytest

from app.agents.model_router import ModelRouter
from app.agents.sdk import run_structured
from app.config import Settings
from app.errors import AppError


class _Batch:
    """Stand-in for a parsed coding batch."""

    def __init__(self, label: str) -> None:
        self.label = label


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    """Build settings that do not touch the developer .env values passed as init args.

    Args:
        tmp_path: Pytest temporary directory.
        **overrides: Settings fields to replace.

    Returns:
        Isolated settings.
    """
    values: dict[str, object] = {
        "openai_api_key": "sk-openai",
        "anthropic_api_key": "sk-ant-test",
        "database_url": f"sqlite:///{(tmp_path / 'studio.db').as_posix()}",
        "storage_root": tmp_path / "storage",
        "session_db_path": tmp_path / "sessions.db",
        "cors_origins": "http://localhost:5173",
        "model_orchestrator": "gpt-6.1-sol",
        "model_questionnaire": "gpt-6.1-sol",
        "model_tabspec": "gpt-6.1-sol",
        "model_analysis": "gpt-6.1-sol",
        "model_coding": "claude-sonnet-5-5",
        "model_validator": "gpt-6.1-sol",
        "model_general": "gpt-6.1-sol",
        "model_fallback": "gpt-6.1-sol",
    }
    values.update(overrides)
    return Settings(**values)


def _install_anthropic(monkeypatch: pytest.MonkeyPatch, messages: object) -> None:
    """Point the Anthropic import at a fake client.

    Args:
        monkeypatch: Pytest monkeypatch.
        messages: Object with a parse method.
    """
    module = types.ModuleType("anthropic")

    class Anthropic:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key
            self.messages = messages

    module.Anthropic = Anthropic
    monkeypatch.setitem(sys.modules, "anthropic", module)


@pytest.mark.asyncio
async def test_coding_role_calls_claude_sonnet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A coding role sends the Claude model id and returns the parsed batch."""
    captured: dict[str, object] = {}

    class Messages:
        def parse(self, **kwargs: object) -> object:
            captured.update(kwargs)
            return types.SimpleNamespace(parsed_output=_Batch("coded"))

    _install_anthropic(monkeypatch, Messages())
    result = await run_structured(
        _settings(tmp_path),
        name="Open-end coding specialist",
        instructions="Use only supplied code ids.",
        prompt="row 1: faster shipping",
        output_type=_Batch,
        role="coding",
        session_id="session-1",
    )
    assert result.label == "coded"
    assert captured["model"] == "claude-sonnet-5-5"
    assert captured["output_format"] is _Batch
    assert captured["max_tokens"] == 16384


@pytest.mark.asyncio
async def test_coding_without_anthropic_key_does_not_call_openai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Claude coding role with a blank key fails before any provider call."""

    def _boom(api_key: str) -> None:
        raise AssertionError(api_key)

    module = types.ModuleType("anthropic")
    module.Anthropic = _boom
    monkeypatch.setitem(sys.modules, "anthropic", module)
    with pytest.raises(AppError) as caught:
        await run_structured(
            _settings(tmp_path, anthropic_api_key="  "),
            name="Open-end coding specialist",
            instructions="Use only supplied code ids.",
            prompt="row 1",
            output_type=_Batch,
            role="coding",
            session_id="session-1",
        )
    assert caught.value.code == "missing_api_key"


@pytest.mark.asyncio
async def test_claude_failure_does_not_fall_back_to_openai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Claude API error stays a model error and does not switch providers."""

    class Messages:
        def parse(self, **kwargs: object) -> object:
            raise RuntimeError("overloaded")

    _install_anthropic(monkeypatch, Messages())
    with pytest.raises(AppError) as caught:
        await run_structured(
            _settings(tmp_path),
            name="Open-end coding specialist",
            instructions="Use only supplied code ids.",
            prompt="row 1",
            output_type=_Batch,
            role="coding",
            session_id="session-1",
        )
    assert caught.value.code == "model_error"
    assert "RuntimeError" in caught.value.message


def test_probe_does_not_mark_claude_missing_when_the_key_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The OpenAI account list is not expected to contain the coding model."""

    class Models:
        def list(self) -> list[object]:
            return [types.SimpleNamespace(id="gpt-6.1-sol")]

    class Client:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key
            self.models = Models()

    monkeypatch.setattr("openai.OpenAI", Client)
    result = ModelRouter(_settings(tmp_path)).probe()
    assert result["available"] is True
    assert result["missing_models"] == []
    assert result["configured"]["coding"] == "claude-sonnet-5-5"


def test_probe_reports_claude_when_the_anthropic_key_is_blank(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A coding model cannot be used until the Anthropic key is present."""

    class Models:
        def list(self) -> list[object]:
            return [types.SimpleNamespace(id="gpt-6.1-sol")]

    class Client:
        def __init__(self, api_key: str) -> None:
            self.models = Models()

    monkeypatch.setattr("openai.OpenAI", Client)
    result = ModelRouter(_settings(tmp_path, anthropic_api_key="")).probe()
    assert result["available"] is False
    assert result["missing_models"] == ["claude-sonnet-5-5"]


def test_probe_hides_the_key_when_openai_listing_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed account listing names the error class and not the key."""

    class Client:
        def __init__(self, api_key: str) -> None:
            raise RuntimeError(f"rejected {api_key}")

    monkeypatch.setattr("openai.OpenAI", Client)
    result = ModelRouter(_settings(tmp_path)).probe()
    assert result["available"] is False
    assert "RuntimeError" in result["reason"]
    assert "sk-openai" not in result["reason"]
    assert "sk-ant-test" not in result["reason"]
