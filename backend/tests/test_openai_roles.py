"""Coding and synthetic calls stand alone on any provider, and coding sees code labels."""

import asyncio

from app.agents import sdk
from app.agents.coding_agent import codeframe_text
from app.config import Settings
from app.schemas.coding import Codeframe, CodeNode


def test_coding_and_synthetic_calls_share_no_session(monkeypatch) -> None:
    seen: dict[str, str] = {}

    async def fake_run(settings, model, name, instructions, prompt, output_type, session_id):
        seen[name] = session_id
        return "ok"

    monkeypatch.setattr(sdk, "_run_model", fake_run)
    settings = Settings(openai_api_key="x", model_call_cache=False)
    for role in ("coding", "synthetic", "analysis"):
        asyncio.run(
            sdk.run_structured(
                settings,
                name=role,
                instructions="",
                prompt="",
                output_type=str,
                role=role,
                session_id="conversation-1",
            )
        )
    assert seen == {"coding": "", "synthetic": "", "analysis": "conversation-1"}


def test_every_role_defaults_to_openai() -> None:
    settings = Settings(_env_file=None)
    for role in ("orchestrator", "coding", "synthetic", "research", "analysis", "general"):
        assert settings.provider_for(settings.model_for(role)) == "openai", role


def test_coding_prompt_names_what_each_code_means() -> None:
    frame = Codeframe(
        codeframe_id="f",
        response_variable="Q27",
        respondent_id_variable="id",
        codes=[
            CodeNode(id="4", label="Simple and quick", definition="Ease of use"),
            CodeNode(id="9", label="Pods cost too much", include_examples=["pods pricey"]),
        ],
    )
    text = codeframe_text(frame)
    assert "4: Simple and quick - Ease of use" in text
    assert "9: Pods cost too much (for example: pods pricey)" in text
