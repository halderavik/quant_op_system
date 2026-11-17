"""Connector accounts: catalog rows, public views, tokens, and tool discovery."""

import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.connectors import client
from app.connectors.catalog import CATALOG, CUSTOM, client_credentials, entry, fill, redirect_uri
from app.connectors.secrets import seal, unseal
from app.errors import AppError
from app.models.tables import ConnectorAccount
from app.util import new_id


def _now() -> datetime:
    """Return the current UTC time.

    Returns:
        Timezone-aware timestamp.
    """
    return datetime.now(timezone.utc)


def ensure_catalog(db: Session) -> None:
    """Create one account row per ready-made connector.

    Args:
        db: Session.
    """
    have = {row.catalog_id for row in db.scalars(select(ConnectorAccount))}
    for item in CATALOG:
        if item.id not in have:
            db.add(
                ConnectorAccount(
                    id=new_id(),
                    catalog_id=item.id,
                    name=item.name,
                    server_url=item.server_url,
                    settings={},
                    status="disconnected",
                    tools=[],
                    created_at=_now(),
                    updated_at=_now(),
                )
            )
    db.flush()


def accounts(db: Session) -> list[ConnectorAccount]:
    """Return every account, ready-made connectors first.

    Args:
        db: Session.

    Returns:
        Account rows.
    """
    ensure_catalog(db)
    order = {item.id: index for index, item in enumerate(CATALOG)}
    rows = list(db.scalars(select(ConnectorAccount)))
    return sorted(rows, key=lambda row: (order.get(row.catalog_id, 99), row.created_at))


def get(db: Session, account_id: str) -> ConnectorAccount:
    """Return one account.

    Args:
        db: Session.
        account_id: Account id.

    Returns:
        Account row.

    Raises:
        AppError: The account does not exist.
    """
    row = db.get(ConnectorAccount, account_id)
    if row is None:
        raise AppError("That connector was not found.", "not_found", 404)
    return row


def connected(db: Session) -> list[ConnectorAccount]:
    """Return accounts that are connected and have tools.

    Args:
        db: Session.

    Returns:
        Connected account rows.
    """
    return [row for row in accounts(db) if row.status == "connected"]


def url_for(settings: Settings, row: ConnectorAccount) -> str:
    """Return the account's MCP endpoint with the tenant filled.

    Args:
        settings: Application settings.
        row: Account.

    Returns:
        Endpoint URL.
    """
    return fill(row.server_url or entry(row.catalog_id).server_url, settings, row.settings)


def public(settings: Settings, row: ConnectorAccount) -> dict[str, Any]:
    """Return an account for the browser. Tokens and client secrets are never included.

    Args:
        settings: Application settings.
        row: Account.

    Returns:
        Public account view with catalog details.
    """
    item = entry(row.catalog_id)
    client_id, client_secret = client_credentials(settings, item)
    scopes = row.settings.get("scopes") or list(item.scopes)
    return {
        "id": row.id,
        "catalog_id": row.catalog_id,
        "name": row.name,
        "category": item.category,
        "description": item.description,
        "auth": item.auth,
        "server_url": url_for(settings, row),
        "status": row.status,
        "error": row.error,
        "configured": item.auth != "oauth" or bool(client_id and client_secret),
        "client_env": [name for name in item.client_env if name],
        "has_token": bool(unseal(settings, row.secret).get("access_token")),
        "status_note": item.status_note,
        "setup": list(item.setup),
        "examples": list(item.examples),
        "docs_url": item.docs_url,
        "redirect_uri": redirect_uri(settings) if item.auth == "oauth" else "",
        "scopes": scopes,
        "tools": [
            {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "read_only": client.is_read_only(tool),
            }
            for tool in row.tools or []
        ],
        "custom": row.catalog_id == CUSTOM.id,
    }


def add_custom(
    db: Session, settings: Settings, *, name: str, server_url: str, token: str
) -> ConnectorAccount:
    """Add a custom MCP server.

    Args:
        db: Session.
        settings: Application settings.
        name: Display name.
        server_url: Streamable HTTP endpoint.
        token: Optional bearer token.

    Returns:
        New account row.

    Raises:
        AppError: The URL is not http or https.
    """
    url = server_url.strip()
    if not url.lower().startswith(("https://", "http://")):
        raise AppError("Enter the server's https:// URL.", "bad_connector_url")
    row = ConnectorAccount(
        id=new_id(),
        catalog_id=CUSTOM.id,
        name=name.strip() or "Custom MCP server",
        server_url=url,
        settings={},
        secret=seal(settings, {"access_token": token.strip()} if token.strip() else {}),
        status="disconnected",
        tools=[],
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(row)
    db.flush()
    return row


def update_settings(
    db: Session,
    row: ConnectorAccount,
    *,
    server_url: str | None,
    scopes: list[str] | None,
    tenant_id: str | None,
    token: str | None,
    settings: Settings,
) -> ConnectorAccount:
    """Change an account's endpoint, scopes, tenant, or token.

    Args:
        db: Session.
        row: Account.
        server_url: New endpoint, or None to keep it.
        scopes: New OAuth scopes, or None to keep them.
        tenant_id: Microsoft tenant id, or None to keep it.
        token: New bearer token for a custom server, or None to keep it.
        settings: Application settings.

    Returns:
        Updated row. It is disconnected so the next test uses the new settings.
    """
    values = dict(row.settings or {})
    if server_url is not None:
        url = server_url.strip()
        if url and not url.lower().startswith(("https://", "http://")):
            raise AppError("Enter the server's https:// URL.", "bad_connector_url")
        row.server_url = url or entry(row.catalog_id).server_url
    if scopes is not None:
        values["scopes"] = [scope.strip() for scope in scopes if scope.strip()]
    if tenant_id is not None:
        values["tenant_id"] = tenant_id.strip()
    if token is not None and row.catalog_id == CUSTOM.id:
        row.secret = seal(settings, {"access_token": token.strip()} if token.strip() else {})
    row.settings = values
    row.status = "disconnected"
    row.tools = []
    row.updated_at = _now()
    db.flush()
    return row


def save_tokens(settings: Settings, row: ConnectorAccount, payload: dict[str, Any]) -> None:
    """Store tokens from an OAuth token response.

    Args:
        settings: Application settings.
        row: Account.
        payload: Token response (access_token, refresh_token, expires_in).
    """
    previous = unseal(settings, row.secret)
    expires_in = payload.get("expires_in")
    values = {
        "access_token": payload.get("access_token", ""),
        # Reason: Google omits the refresh token on re-consent; keep the old one.
        "refresh_token": payload.get("refresh_token") or previous.get("refresh_token", ""),
        "expires_at": time.time() + float(expires_in) if expires_in else 0,
    }
    row.secret = seal(settings, values)
    row.updated_at = _now()


def disconnect(db: Session, row: ConnectorAccount) -> None:
    """Forget an account's tokens and tools. A custom server is removed.

    Args:
        db: Session.
        row: Account.
    """
    if row.catalog_id == CUSTOM.id:
        db.delete(row)
    else:
        row.secret = ""
        row.status = "disconnected"
        row.tools = []
        row.error = None
        row.updated_at = _now()
    db.flush()


async def token_for(db: Session, settings: Settings, row: ConnectorAccount) -> str:
    """Return a usable access token, refreshing an expired OAuth token.

    Args:
        db: Session.
        settings: Application settings.
        row: Account.

    Returns:
        Bearer token. Empty for a custom server without one.
    """
    values = unseal(settings, row.secret)
    expires_at = float(values.get("expires_at") or 0)
    if expires_at and expires_at - time.time() < 60 and values.get("refresh_token"):
        from app.connectors.oauth import refresh

        payload = await refresh(settings, row, values["refresh_token"])
        save_tokens(settings, row, payload)
        db.flush()
        values = unseal(settings, row.secret)
    return str(values.get("access_token") or "")


async def test(db: Session, settings: Settings, row: ConnectorAccount) -> ConnectorAccount:
    """Connect, list tools, and record the result.

    Args:
        db: Session.
        settings: Application settings.
        row: Account.

    Returns:
        The account, connected or with an error.
    """
    item = entry(row.catalog_id)
    try:
        token = await token_for(db, settings, row)
        if item.auth == "oauth" and not token:
            raise AppError("Sign in to connect this connector.", "connector_signin")
        tools = await client.list_tools(
            url_for(settings, row), token, timeout=settings.connector_timeout_seconds
        )
    except AppError as exc:
        row.status = "error"
        row.error = exc.message
        row.tools = []
    else:
        row.status = "connected"
        row.error = None
        row.tools = tools
    row.updated_at = _now()
    db.flush()
    return row
