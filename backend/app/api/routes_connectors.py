"""Connector routes: catalog, sign-in, tests, and actions waiting for approval."""

import html
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.connectors import agent, oauth, store
from app.connectors.catalog import entry
from app.errors import AppError
from app.models.tables import ConnectorAction
from app.repositories.records import ProjectRepository

router = APIRouter()


class CustomConnectorIn(BaseModel):
    """A custom MCP server."""

    name: str = ""
    server_url: str
    token: str = ""


class ConnectorSettingsIn(BaseModel):
    """Editable connector settings. Omitted fields keep their value."""

    server_url: str | None = None
    scopes: list[str] | None = None
    tenant_id: str | None = None
    token: str | None = None


def _action_view(db: Session, action: ConnectorAction) -> dict[str, Any]:
    """Return an action for the browser. File placeholders stay as placeholders.

    Args:
        db: Session.
        action: Action row.

    Returns:
        Public action view.
    """
    try:
        name = store.get(db, action.account_id).name
    except AppError:
        name = "Removed connector"
    return {
        "id": action.id,
        "connector": name,
        "tool": action.tool,
        "summary": action.summary,
        "arguments": action.arguments,
        "display": agent.describe_arguments(db, action.project_id, action.arguments or {}),
        "status": action.status,
        "result": action.result,
        "created_at": action.created_at.isoformat(),
    }


@router.get("/connectors")
def list_connectors(request: Request, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """List ready-made and custom connectors with their status.

    Args:
        request: Current request.
        db: Session.

    Returns:
        Public connector views.
    """
    settings = request.app.state.settings
    rows = store.accounts(db)
    db.commit()
    return [store.public(settings, row) for row in rows]


@router.post("/connectors/custom", status_code=201)
async def add_custom(
    body: CustomConnectorIn, request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Add a custom MCP server and test it.

    Args:
        body: Name, URL, and optional token.
        request: Current request.
        db: Session.

    Returns:
        The connector after its first test.
    """
    settings = request.app.state.settings
    row = store.add_custom(db, settings, name=body.name, server_url=body.server_url, token=body.token)
    await store.test(db, settings, row)
    db.commit()
    return store.public(settings, row)


@router.patch("/connectors/{account_id}")
def update_connector(
    account_id: str, body: ConnectorSettingsIn, request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Change a connector's URL, scopes, tenant, or token.

    Args:
        account_id: Connector id.
        body: Settings to change.
        request: Current request.
        db: Session.

    Returns:
        Updated connector.
    """
    settings = request.app.state.settings
    row = store.update_settings(
        db, store.get(db, account_id),
        server_url=body.server_url, scopes=body.scopes, tenant_id=body.tenant_id,
        token=body.token, settings=settings,
    )
    db.commit()
    return store.public(settings, row)


@router.post("/connectors/{account_id}/connect")
async def connect(account_id: str, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Start sign-in, or test a token-based connector.

    Args:
        account_id: Connector id.
        request: Current request.
        db: Session.

    Returns:
        ``authorize_url`` to open for OAuth connectors, otherwise the tested connector.
    """
    settings = request.app.state.settings
    row = store.get(db, account_id)
    if entry(row.catalog_id).auth == "oauth":
        return {"authorize_url": await oauth.start(settings, row)}
    await store.test(db, settings, row)
    db.commit()
    return {"connector": store.public(settings, row)}


@router.post("/connectors/{account_id}/test")
async def test_connector(
    account_id: str, request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Reconnect and list the connector's tools.

    Args:
        account_id: Connector id.
        request: Current request.
        db: Session.

    Returns:
        The connector after the test.
    """
    settings = request.app.state.settings
    row = await store.test(db, settings, store.get(db, account_id))
    db.commit()
    return store.public(settings, row)


@router.post("/connectors/{account_id}/disconnect")
def disconnect(account_id: str, request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    """Forget a connector's tokens. A custom server is removed.

    Args:
        account_id: Connector id.
        request: Current request.
        db: Session.

    Returns:
        Status.
    """
    store.disconnect(db, store.get(db, account_id))
    db.commit()
    return {"status": "disconnected"}


@router.get("/connectors/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(
    request: Request,
    state: str = "",
    code: str = "",
    error: str = "",
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Finish a provider sign-in and close the window.

    Args:
        request: Current request.
        state: OAuth state.
        code: Authorization code.
        error: Provider error.
        db: Session.

    Returns:
        A small page that tells the studio window and closes itself.
    """
    settings = request.app.state.settings
    name = "The connector"
    try:
        pending = oauth.claim(state)
        row = store.get(db, pending.account_id)
        name = row.name
        if error or not code:
            raise AppError(f"Sign-in was cancelled ({error or 'no code'}).", "connector_signin")
        payload = await oauth.exchange(settings, row, pending, code)
        store.save_tokens(settings, row, payload)
        await store.test(db, settings, row)
        db.commit()
        ok = row.status == "connected"
        message = f"{name} is connected." if ok else f"{name}: {row.error}"
    except AppError as exc:
        ok, message = False, exc.message
    return HTMLResponse(_callback_page(ok, message))


def _callback_page(ok: bool, message: str) -> str:
    """Render the sign-in result page.

    Args:
        ok: Whether the connector connected.
        message: Message for the user. Never contains tokens.

    Returns:
        HTML.
    """
    safe = html.escape(message)
    status = "connected" if ok else "error"
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Quant OS connector</title>
<style>body{{font-family:system-ui,sans-serif;display:grid;place-items:center;height:100vh;margin:0;background:#f7f7f8;color:#1d1d1f}}
main{{background:#fff;border:1px solid #ddd;border-radius:12px;padding:28px 32px;max-width:420px;text-align:center}}</style></head>
<body><main><p>{safe}</p><p style="color:#666;font-size:14px">You can close this window.</p></main>
<script>try{{window.opener&&window.opener.postMessage({{type:"quantos-connector",status:"{status}"}},"*")}}catch(e){{}}
setTimeout(function(){{window.close()}},1500)</script></body></html>"""


@router.get("/projects/{project_id}/connector-actions")
def list_actions(project_id: str, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """List a project's connector actions, newest first.

    Args:
        project_id: Project id.
        db: Session.

    Returns:
        Action views.
    """
    ProjectRepository(db).get(project_id)
    return [_action_view(db, action) for action in agent.pending_actions(db, project_id)[:50]]


def _action(db: Session, action_id: str) -> ConnectorAction:
    """Return one action.

    Args:
        db: Session.
        action_id: Action id.

    Returns:
        Action row.
    """
    row = db.get(ConnectorAction, action_id)
    if row is None:
        raise AppError("That step was not found.", "not_found", 404)
    return row


@router.post("/connector-actions/{action_id}/approve")
async def approve_action(
    action_id: str, request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Run an action the researcher approved.

    Args:
        action_id: Action id.
        request: Current request.
        db: Session.

    Returns:
        The action after it ran.
    """
    action = await agent.approve(
        db, request.app.state.storage, request.app.state.settings, _action(db, action_id)
    )
    db.commit()
    return _action_view(db, action)


@router.post("/connector-actions/{action_id}/cancel")
def cancel_action(action_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Cancel an action.

    Args:
        action_id: Action id.
        db: Session.

    Returns:
        The cancelled action.
    """
    action = agent.cancel(db, _action(db, action_id))
    db.commit()
    return _action_view(db, action)
