"""OAuth sign-in for connectors: discovery, PKCE authorization, token exchange, refresh."""

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from app.config import Settings
from app.connectors.catalog import client_credentials, entry, fill, redirect_uri
from app.errors import AppError
from app.models.tables import ConnectorAccount

_STATE_TTL = 600


@dataclass
class _Pending:
    """One sign-in waiting for the provider's redirect."""

    account_id: str
    verifier: str
    token_url: str
    created: float


# Reason: the studio is one local process; pending sign-ins live for ten minutes.
_PENDING: dict[str, _Pending] = {}


async def _get_json(http: httpx.AsyncClient, url: str) -> dict[str, Any] | None:
    """Fetch JSON metadata, or None when the URL has none.

    Args:
        http: HTTP client.
        url: Metadata URL.

    Returns:
        Parsed JSON object or None.
    """
    try:
        response = await http.get(url)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        body = response.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


async def discover(server_url: str) -> tuple[str, str] | None:
    """Find the authorization and token endpoints from the MCP server's metadata.

    Follows RFC 9728 (protected resource metadata) and RFC 8414 (authorization
    server metadata), with OpenID configuration as a fallback.

    Args:
        server_url: MCP endpoint.

    Returns:
        (authorization endpoint, token endpoint), or None when discovery fails.
    """
    parts = urlsplit(server_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    path = parts.path.rstrip("/")
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as http:
        resource = None
        for url in (
            f"{origin}/.well-known/oauth-protected-resource{path}",
            f"{origin}/.well-known/oauth-protected-resource",
        ):
            resource = await _get_json(http, url)
            if resource and resource.get("authorization_servers"):
                break
        servers = (resource or {}).get("authorization_servers") or [origin]
        issuer = str(servers[0]).rstrip("/")
        issuer_parts = urlsplit(issuer)
        issuer_origin = f"{issuer_parts.scheme}://{issuer_parts.netloc}"
        issuer_path = issuer_parts.path.rstrip("/")
        for url in (
            f"{issuer_origin}/.well-known/oauth-authorization-server{issuer_path}",
            f"{issuer_origin}/.well-known/openid-configuration{issuer_path}",
            f"{issuer}/.well-known/openid-configuration",
        ):
            meta = await _get_json(http, url)
            if meta and meta.get("authorization_endpoint") and meta.get("token_endpoint"):
                return str(meta["authorization_endpoint"]), str(meta["token_endpoint"])
    return None


def _challenge(verifier: str) -> str:
    """Return the S256 PKCE challenge.

    Args:
        verifier: Code verifier.

    Returns:
        URL-safe challenge without padding.
    """
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


async def start(settings: Settings, row: ConnectorAccount) -> str:
    """Build the provider sign-in URL for an account.

    Args:
        settings: Application settings.
        row: Account.

    Returns:
        Authorization URL to open in a browser window.

    Raises:
        AppError: The OAuth client is not configured.
    """
    item = entry(row.catalog_id)
    client_id, client_secret = client_credentials(settings, item)
    if not (client_id and client_secret):
        names = " and ".join(name for name in item.client_env if name)
        raise AppError(
            f"{item.name} is not set up yet. Add {names} to backend/.env and restart the backend. "
            "The setup steps are on the connector card.",
            "connector_not_configured",
        )
    authorize_url = fill(item.authorize_url, settings, row.settings)
    token_url = fill(item.token_url, settings, row.settings)
    if not (authorize_url and token_url):
        found = await discover(fill(row.server_url or item.server_url, settings, row.settings))
        if found is None:
            raise AppError(
                f"{item.name} did not publish its sign-in endpoints.", "connector_discovery"
            )
        authorize_url, token_url = found
    _expire()
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    _PENDING[state] = _Pending(row.id, verifier, token_url, time.time())
    scopes = row.settings.get("scopes") or list(item.scopes)
    query = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri(settings),
        "state": state,
        "code_challenge": _challenge(verifier),
        "code_challenge_method": "S256",
        **item.extra_authorize,
    }
    if scopes:
        # Reason: Slack's user-token flow takes scopes as a comma list under user_scope.
        if row.catalog_id == "slack":
            query["user_scope"] = ",".join(scopes)
        else:
            query["scope"] = " ".join(scopes)
    separator = "&" if "?" in authorize_url else "?"
    return f"{authorize_url}{separator}{urlencode(query)}"


def claim(state: str) -> _Pending:
    """Take a pending sign-in by its state value.

    Args:
        state: OAuth state from the redirect.

    Returns:
        The pending sign-in.

    Raises:
        AppError: The state is unknown or expired.
    """
    _expire()
    pending = _PENDING.pop(state, None)
    if pending is None:
        raise AppError("This sign-in link expired. Start the connection again.", "connector_state")
    return pending


async def exchange(
    settings: Settings, row: ConnectorAccount, pending: _Pending, code: str
) -> dict[str, Any]:
    """Exchange an authorization code for tokens.

    Args:
        settings: Application settings.
        row: Account.
        pending: The pending sign-in.
        code: Authorization code.

    Returns:
        Token response.
    """
    client_id, client_secret = client_credentials(settings, entry(row.catalog_id))
    return await _token_request(
        pending.token_url,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(settings),
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": pending.verifier,
        },
    )


async def refresh(settings: Settings, row: ConnectorAccount, refresh_token: str) -> dict[str, Any]:
    """Refresh an access token.

    Args:
        settings: Application settings.
        row: Account.
        refresh_token: Stored refresh token.

    Returns:
        Token response.
    """
    item = entry(row.catalog_id)
    client_id, client_secret = client_credentials(settings, item)
    token_url = fill(item.token_url, settings, row.settings)
    if not token_url:
        found = await discover(fill(row.server_url or item.server_url, settings, row.settings))
        if found is None:
            raise AppError("Reconnect this connector.", "connector_signin")
        token_url = found[1]
    return await _token_request(
        token_url,
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )


async def _token_request(url: str, form: dict[str, str]) -> dict[str, Any]:
    """Post to a token endpoint and normalize the response.

    Args:
        url: Token endpoint.
        form: Form fields.

    Returns:
        Token response with access_token at the top level.

    Raises:
        AppError: The provider refused the request.
    """
    async with httpx.AsyncClient(timeout=20) as http:
        try:
            response = await http.post(url, data=form, headers={"Accept": "application/json"})
            body = response.json()
        except (httpx.HTTPError, ValueError):
            raise AppError("The sign-in provider did not answer.", "connector_token") from None
    if not isinstance(body, dict):
        raise AppError("The sign-in provider returned an unexpected answer.", "connector_token")
    # Reason: Slack's user flow nests the user token under authed_user and reports ok=false on errors.
    if body.get("ok") is False or response.status_code >= 400 or "error" in body:
        reason = str(body.get("error_description") or body.get("error") or response.status_code)
        raise AppError(f"The sign-in was refused ({reason}).", "connector_token")
    if not body.get("access_token") and isinstance(body.get("authed_user"), dict):
        body = {**body, **body["authed_user"]}
    if not body.get("access_token"):
        raise AppError("The sign-in provider returned no access token.", "connector_token")
    return body


def _expire() -> None:
    """Drop pending sign-ins older than the TTL."""
    cutoff = time.time() - _STATE_TTL
    for key in [key for key, value in _PENDING.items() if value.created < cutoff]:
        _PENDING.pop(key, None)
