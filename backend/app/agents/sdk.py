"""Model calls for specialists. API keys stay in the server process."""

import asyncio
import json
import os
from contextvars import ContextVar

from app.config import Settings
from app.errors import AppError

# Roles whose calls each stand alone, whichever provider serves them.
STATELESS_ROLES = frozenset({"coding", "synthetic"})


async def run_structured(
    settings: Settings,
    *,
    name: str,
    instructions: str,
    prompt: str,
    output_type: type,
    role: str,
    session_id: str,
    cache: bool = False,
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
        session_id: Persistent SDK session id. Used for OpenAI calls, except for the
            roles in ``STATELESS_ROLES``, which never share history between calls.
        cache: Reuse a finished answer to the identical call, and keep this one, so a
            retried import or plan continues where it stopped.

    Returns:
        Parsed structured output.
    """
    from app.services import call_cache

    cache = cache and getattr(settings, "model_call_cache", False)
    model = settings.model_for(role)
    if role in STATELESS_ROLES:
        # Reason: each coding batch or synthetic slice carries everything it needs; on
        # OpenAI a shared session would feed earlier batches into later ones.
        session_id = ""
    key = call_cache.cache_key(model, instructions, prompt, output_type) if cache else ""
    if cache and hasattr(output_type, "model_validate_json"):
        saved = call_cache.load(settings.storage_root, key, output_type)
        if saved is not None:
            return saved
    try:
        answer = await _run_model(
            settings, model, name, instructions, prompt, output_type, session_id
        )
    except AppError as exc:
        backup = backup_model(settings, model)
        if backup is None or not provider_failure(exc):
            raise
        note = (
            f"The {settings.provider_for(model).title()} model was unavailable "
            f"({exc.message.rstrip('.')}), so {backup} was used instead."
        )
        record_model_note(note)
        answer = await _run_model(
            settings, backup, name, instructions, prompt, output_type, session_id
        )
    if cache and hasattr(answer, "model_dump"):
        call_cache.save(settings.storage_root, key, answer)
    return answer


async def _run_model(
    settings: Settings,
    model: str,
    name: str,
    instructions: str,
    prompt: str,
    output_type: type,
    session_id: str,
):
    """Send one call to the provider that serves ``model``."""
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


# Notes about backup-model use, collected per task so the chat reply can mention them.
_MODEL_NOTES: ContextVar[list[str] | None] = ContextVar("model_notes", default=None)
_PROVIDER_ERRORS = {
    "RateLimitError",
    "APIConnectionError",
    "APITimeoutError",
    "InternalServerError",
    "AuthenticationError",
    "PermissionDeniedError",
    "ServiceUnavailableError",
    "OverloadedError",
}


def start_model_notes() -> list[str]:
    """Begin collecting backup-model notes for the current task."""
    notes: list[str] = []
    _MODEL_NOTES.set(notes)
    return notes


def record_model_note(note: str) -> None:
    """Remember that a backup model ran, once per distinct note."""
    notes = _MODEL_NOTES.get()
    if notes is not None and note not in notes:
        notes.append(note)


def backup_model(settings: Settings, model: str) -> str | None:
    """The other provider's model, when backups are on and that provider has a key."""
    if not settings.model_backup_enabled:
        return None
    if settings.provider_for(model) == "anthropic":
        return settings.model_backup_openai if settings.openai_api_key.strip() else None
    return settings.model_backup_anthropic if settings.anthropic_api_key.strip() else None


def provider_failure(exc: AppError) -> bool:
    """Whether a call failed because of the provider (credits, limits, outage, key), not the answer."""
    if exc.code == "missing_api_key":
        return True
    if exc.code != "model_error":
        return False
    cause = exc.__cause__
    if cause is None:
        return False
    text = str(cause).lower()
    status = getattr(cause, "status_code", None)
    return (
        cause.__class__.__name__ in _PROVIDER_ERRORS
        or "credit" in text
        or "quota" in text
        or "billing" in text
        or "overloaded" in text
        or (isinstance(status, int) and (status in {401, 403, 429} or status >= 500))
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
    from pydantic import ValidationError

    from app.agents.claude_schema import claude_schema

    client = Anthropic(api_key=settings.anthropic_api_key)
    schema = claude_schema(output_type)

    def _call(system: str, constrained: bool):
        # Reason: streaming keeps long answers (a whole questionnaire section) under
        # HTTP timeouts. Server-side fallbacks retry a refused request on another model.
        output_config: dict = {"effort": "medium"}
        if constrained:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        with client.beta.messages.stream(
            model=model,
            max_tokens=64000,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config=output_config,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            return stream.get_final_message()

    # Reason: a large schema can be too big for Claude to compile into a grammar. Then
    # the schema goes in the instructions and the answer is validated in code instead.
    key = output_type.__qualname__
    unconstrained = (
        f"{instructions}\n\nAnswer with one JSON object only, no other text, matching this "
        f"JSON schema:\n{json.dumps(schema)}"
    )
    attempts = (
        [(unconstrained, False), (unconstrained, False)]
        if key in _TOO_LARGE
        else [(instructions, True)]
    )
    last_error = "The model's answer did not match the expected structure."
    while attempts:
        system, constrained = attempts.pop(0)
        try:
            response = await asyncio.to_thread(_call, system, constrained)
        except Exception as exc:
            if constrained and "grammar is too large" in str(exc):
                _TOO_LARGE.add(key)
                attempts = [(unconstrained, False), (unconstrained, False)]
                continue
            raise AppError(_failure_message(exc), "model_error", 502) from exc
        if response.stop_reason == "refusal":
            raise AppError("The model declined this request.", "model_refusal", 502)
        if response.stop_reason == "max_tokens":
            raise AppError("The model's answer was too long and was cut off.", "model_error", 502)
        text = "".join(block.text for block in response.content if block.type == "text")
        try:
            return output_type.model_validate_json(_json_body(text))
        except ValidationError as exc:
            last_error = f"The model's answer did not match the expected structure ({exc.error_count()} problems)."
            if not constrained and attempts:
                continue
            raise AppError(last_error, "model_error", 502) from exc
    raise AppError(last_error, "model_error", 502)


# Answer types whose schema Claude would not compile; later calls skip that attempt.
_TOO_LARGE: set[str] = set()


def _json_body(text: str) -> str:
    """The JSON object in a reply, without a code fence or words around it."""
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


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
    session = SQLiteSession(session_id, settings.session_db_path) if session_id else None
    try:
        result = await Runner.run(agent, prompt, session=session)
    except Exception as exc:
        fallback = settings.model_fallback
        if fallback and fallback != model and "model" in str(exc).lower():
            agent.model = fallback
            result = await Runner.run(agent, prompt, session=session)
        else:
            raise AppError(
                _failure_message(exc),
                "model_error",
                502,
            ) from exc
    return result.final_output


def _failure_message(exc: Exception) -> str:
    """Say why a model call failed in words the user can act on.

    Args:
        exc: Error from the provider SDK.

    Returns:
        One sentence. Out-of-credit and rate-limit errors are named.
    """
    text = str(exc).lower()
    if "credit" in text or "quota" in text or "billing" in text:
        return "The model provider account has no credits left. Add credits, then try again."
    if exc.__class__.__name__ == "RateLimitError" or "429" in text:
        return "The model provider is rate limiting requests. Wait a minute, then try again."
    return f"The model call failed ({exc.__class__.__name__}). Check the model id and key."
