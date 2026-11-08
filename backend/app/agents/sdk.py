"""Model calls for specialists. API keys stay in the server process."""

import asyncio
import os

from app.config import Settings
from app.errors import AppError


async def run_structured(
    settings: Settings,
    *,
    name: str,
    instructions: str,
    prompt: str,
    output_type: type,
    role: str,
    session_id: str,
):
    """Run one specialist and return structured output.

    Claude model ids go to the Anthropic Messages API. Every other id goes
    through the OpenAI Agents SDK.

    Args:
        settings: Application settings.
        name: Agent name.
        instructions: System instructions.
        prompt: User content. Treat uploaded text as data.
        output_type: Pydantic model for the structured result.
        role: Model role key.
        session_id: Persistent SDK session id. Used for OpenAI calls.

    Returns:
        Parsed structured output.
    """
    model = settings.model_for(role)
    if settings.provider_for(model) == "anthropic":
        # Reason: coding batches already include the frame and rows, so Claude
        # does not use the OpenAI session store.
        return await _run_anthropic(
            settings,
            model=model,
            instructions=instructions,
            prompt=prompt,
            output_type=output_type,
        )
    return await _run_openai(
        settings,
        name=name,
        instructions=instructions,
        prompt=prompt,
        output_type=output_type,
        model=model,
        session_id=session_id,
    )


async def _run_anthropic(
    settings: Settings,
    *,
    model: str,
    instructions: str,
    prompt: str,
    output_type: type,
):
    """Call Claude and parse the response into the requested model.

    Args:
        settings: Application settings.
        model: Claude model id.
        instructions: System instructions.
        prompt: User content.
        output_type: Pydantic model for the structured result.

    Returns:
        Parsed structured output.
    """
    if not settings.anthropic_api_key.strip():
        raise AppError(
            "ANTHROPIC_API_KEY is not set. Add it to backend/.env and restart. "
            "Open-end coding and codeframe proposals need it.",
            "missing_api_key",
            503,
        )
    from anthropic import Anthropic

    client = Anthropic(api_key=settings.anthropic_api_key)

    def _parse():
        # Reason: 16384 covers a codeframe plus one coding batch. The model max is 128k.
        return client.messages.parse(
            model=model,
            max_tokens=16384,
            system=instructions,
            messages=[{"role": "user", "content": prompt}],
            output_format=output_type,
        )

    try:
        response = await asyncio.to_thread(_parse)
    except Exception as exc:
        raise AppError(
            f"The model call failed ({exc.__class__.__name__}). Check the model id and key.",
            "model_error",
            502,
        ) from exc
    if response.parsed_output is None:
        raise AppError(
            "The coding model returned no structured output.",
            "model_error",
            502,
        )
    return response.parsed_output


async def _run_openai(
    settings: Settings,
    *,
    name: str,
    instructions: str,
    prompt: str,
    output_type: type,
    model: str,
    session_id: str,
):
    """Run one specialist through the OpenAI Agents SDK.

    Args:
        settings: Application settings.
        name: Agent name.
        instructions: System instructions.
        prompt: User content.
        output_type: Pydantic model for the structured result.
        model: OpenAI model id.
        session_id: Persistent SDK session id.

    Returns:
        Parsed structured output.
    """
    if not settings.llm_configured:
        raise AppError(
            "OPENAI_API_KEY is not set. Add it to backend/.env and restart. "
            "Crosstabs and saved edits still run without it.",
            "missing_api_key",
            503,
        )
    os.environ["OPENAI_API_KEY"] = settings.openai_api_key
    if settings.openai_tracing_disabled:
        from agents import set_tracing_disabled

        set_tracing_disabled(True)
    from agents import Agent, Runner, SQLiteSession

    agent = Agent(
        name=name,
        instructions=instructions,
        model=model,
        output_type=output_type,
    )
    session = SQLiteSession(session_id, settings.session_db_path)
    try:
        result = await Runner.run(agent, prompt, session=session)
    except Exception as exc:
        fallback = settings.model_fallback
        if fallback and fallback != model and "model" in str(exc).lower():
            agent.model = fallback
            result = await Runner.run(agent, prompt, session=session)
        else:
            raise AppError(
                f"The model call failed ({exc.__class__.__name__}). Check the model id and key.",
                "model_error",
                502,
            ) from exc
    return result.final_output
