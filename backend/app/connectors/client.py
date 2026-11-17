"""Call remote MCP servers over streamable HTTP."""

import base64
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

from app.errors import AppError

# Reason: tools without a read-only annotation are judged by name; anything else needs approval.
_READ_NAME = re.compile(
    r"^(?:search|list|get|read|fetch|find|download|describe|query|lookup|view|show|export)(?:_|[A-Z]|$)",
    re.I,
)
_MAX_TEXT = 200_000


@dataclass
class ToolOutcome:
    """What a tool call returned.

    Attributes:
        text: Text and structured content joined for the agent and the user.
        is_error: Whether the server reported a tool error.
        files: Binary or text resources returned by the tool, as (name, bytes, media type).
    """

    text: str
    is_error: bool = False
    files: list[tuple[str, bytes, str]] = field(default_factory=list)


def is_read_only(tool: dict[str, Any]) -> bool:
    """Return whether a tool only reads.

    Args:
        tool: Tool summary from :func:`list_tools`.

    Returns:
        True when the server marks it read-only, or when it has no hint and a reading name.
    """
    hint = tool.get("read_only_hint")
    if hint is not None:
        return bool(hint)
    return bool(_READ_NAME.match(str(tool.get("name") or "")))


@asynccontextmanager
async def open_session(url: str, token: str, timeout: float) -> AsyncIterator[ClientSession]:
    """Open an initialized MCP session.

    Args:
        url: Streamable HTTP endpoint.
        token: Bearer token. Empty for servers without auth.
        timeout: Read timeout in seconds.

    Yields:
        Initialized client session.
    """
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with create_mcp_http_client(headers=headers) as http:
        async with streamable_http_client(url, http_client=http) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timeout) as session:
                await session.initialize()
                yield session


async def list_tools(url: str, token: str, timeout: float = 30) -> list[dict[str, Any]]:
    """List a server's tools.

    Args:
        url: Streamable HTTP endpoint.
        token: Bearer token.
        timeout: Read timeout in seconds.

    Returns:
        Tool summaries with name, description, input schema, and read-only hint.

    Raises:
        AppError: The server could not be reached or refused the token.
    """
    try:
        async with open_session(url, token, timeout) as session:
            tools: list[Any] = []
            cursor = None
            for _ in range(20):
                params = None
                if cursor:
                    from mcp.types import PaginatedRequestParams

                    params = PaginatedRequestParams(cursor=cursor)
                page = await session.list_tools(params=params)
                tools.extend(page.tools)
                cursor = getattr(page, "next_cursor", None)
                if not cursor:
                    break
    except AppError:
        raise
    except BaseException as exc:  # noqa: BLE001 - anyio wraps transport errors in groups
        raise AppError(await _failure(url, token, exc), "connector_unreachable", 502) from None
    summaries = []
    for tool in tools:
        hint = getattr(tool.annotations, "read_only_hint", None) if tool.annotations else None
        summaries.append(
            {
                "name": tool.name,
                "description": (tool.description or "")[:600],
                "input_schema": tool.input_schema or {},
                "read_only_hint": hint,
            }
        )
    return summaries


async def call_tool(
    url: str, token: str, name: str, arguments: dict[str, Any], timeout: float = 60
) -> ToolOutcome:
    """Call one tool.

    Args:
        url: Streamable HTTP endpoint.
        token: Bearer token.
        name: Tool name.
        arguments: Tool arguments.
        timeout: Read timeout in seconds.

    Returns:
        The tool outcome.

    Raises:
        AppError: The server could not be reached.
    """
    try:
        async with open_session(url, token, timeout) as session:
            result = await session.call_tool(name, arguments, read_timeout_seconds=timeout)
    except BaseException as exc:  # noqa: BLE001 - anyio wraps transport errors in groups
        raise AppError(await _failure(url, token, exc), "connector_unreachable", 502) from None
    return _outcome(result)


def _outcome(result: Any) -> ToolOutcome:
    """Turn a CallToolResult into text and files.

    Args:
        result: MCP result.

    Returns:
        Tool outcome.
    """
    parts: list[str] = []
    files: list[tuple[str, bytes, str]] = []
    for item in getattr(result, "content", None) or []:
        kind = getattr(item, "type", "")
        if kind == "text":
            parts.append(item.text)
        elif kind == "resource":
            resource = item.resource
            name = str(resource.uri).rsplit("/", 1)[-1] or "resource"
            media = resource.mime_type or "application/octet-stream"
            if getattr(resource, "text", None) is not None:
                parts.append(resource.text)
                files.append((name, resource.text.encode("utf-8"), media))
            elif getattr(resource, "blob", None):
                files.append((name, base64.b64decode(resource.blob), media))
                parts.append(f"[file {name}, {media}]")
        elif kind == "resource_link":
            parts.append(f"[link {getattr(item, 'name', '')}: {getattr(item, 'uri', '')}]")
        elif kind == "image":
            parts.append("[image]")
    structured = getattr(result, "structured_content", None)
    if structured and not parts:
        parts.append(json.dumps(structured, ensure_ascii=False))
    text = "\n".join(parts)[:_MAX_TEXT]
    return ToolOutcome(text=text, is_error=bool(getattr(result, "is_error", False)), files=files)


async def _failure(url: str, token: str, exc: BaseException) -> str:
    """Describe a transport failure without leaking tokens.

    Args:
        url: Endpoint that failed.
        token: Bearer token used.
        exc: Exception or exception group.

    Returns:
        User-facing message.
    """
    leaf: BaseException = exc
    while isinstance(leaf, BaseExceptionGroup) and leaf.exceptions:
        leaf = leaf.exceptions[0]
    if isinstance(leaf, (KeyboardInterrupt, SystemExit)):
        raise leaf
    # Reason: the MCP client hides HTTP status codes, so ask the server directly.
    import httpx

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    headers["Accept"] = "application/json, text/event-stream"
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            response = await http.post(url, headers=headers, json={})
        status = response.status_code
    except httpx.HTTPError:
        return "The connector server could not be reached. Check the URL and your network."
    if status in {401, 403}:
        return "The connector refused the credentials. Reconnect it from Connectors."
    if status == 404:
        return "The connector URL was not found. Check the server URL."
    return f"The connector call failed ({leaf.__class__.__name__}: {str(leaf)[:200]})."
