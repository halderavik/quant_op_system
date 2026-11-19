"""Connectors: catalog, sign-in URL, custom MCP servers, the connector agent, and approvals."""

import socket
from collections.abc import Iterator
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agents.intent import product_lock
from app.config import Settings
from app.connectors import oauth
from app.connectors.agent import ConnectorPlan, PlannedCall
from app.connectors.secrets import seal, unseal
from app.main import create_app
from tests.conftest import create_project
from tests.mock_mcp_server import STATE, serve_in_thread

TOKEN = "stand-in-token"


@pytest.fixture(scope="module")
def mcp_url() -> Iterator[str]:
    """Serve the stand-in MCP server for this module.

    Yields:
        Its MCP endpoint.
    """
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    server = serve_in_thread(port, TOKEN)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True


def _connect_custom(client: TestClient, url: str, token: str = TOKEN) -> dict:
    """Add the stand-in server as a custom connector.

    Args:
        client: Test client.
        url: MCP endpoint.
        token: Bearer token.

    Returns:
        Connector JSON.
    """
    response = client.post(
        "/api/connectors/custom",
        json={"name": "Stand-in workspace", "server_url": url, "token": token},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_catalog_lists_ready_made_connectors_without_secrets(client: TestClient) -> None:
    """Drive, Slack, and Microsoft 365 are listed, unconfigured, with setup steps."""
    body = client.get("/api/connectors").json()
    ids = [item["catalog_id"] for item in body]
    assert ids == ["google_drive", "google_drive_api", "slack", "microsoft_365"]
    drive = body[0]
    assert drive["configured"] is False
    assert drive["status"] == "disconnected"
    assert drive["setup"] and drive["redirect_uri"].endswith("/api/connectors/oauth/callback")
    assert "GOOGLE_MCP_CLIENT_ID" in drive["client_env"]
    assert all("secret" not in item and "token" not in item for item in body)


def test_oauth_connect_needs_the_client_in_env(client: TestClient) -> None:
    """Connecting Drive without a client id explains what to add."""
    drive = client.get("/api/connectors").json()[0]
    response = client.post(f"/api/connectors/{drive['id']}/connect")
    assert response.status_code == 400
    assert "GOOGLE_MCP_CLIENT_ID" in response.json()["error"]["message"]


def test_oauth_start_builds_a_pkce_sign_in_url(settings: Settings) -> None:
    """With a client configured, connect returns the Google sign-in URL with PKCE."""
    configured = settings.model_copy(
        update={"google_mcp_client_id": "client-123", "google_mcp_client_secret": "shh"}
    )
    with TestClient(create_app(configured)) as client:
        drive = client.get("/api/connectors").json()[0]
        assert drive["configured"] is True
        url = client.post(f"/api/connectors/{drive['id']}/connect").json()["authorize_url"]
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    assert parts.netloc == "accounts.google.com"
    assert query["client_id"] == ["client-123"]
    assert query["code_challenge_method"] == ["S256"]
    assert "https://www.googleapis.com/auth/drive.file" in query["scope"][0]
    assert query["access_type"] == ["offline"]
    assert "shh" not in url


async def test_slack_token_response_uses_the_user_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Slack nests the user token under authed_user; the exchange lifts it."""

    def _handler(request: httpx.Request) -> httpx.Response:
        assert b"code_verifier" in request.content
        return httpx.Response(
            200, json={"ok": True, "authed_user": {"access_token": "xoxp-1", "refresh_token": "r"}}
        )

    real = httpx.AsyncClient
    monkeypatch.setattr(
        oauth.httpx, "AsyncClient", lambda **kwargs: real(transport=httpx.MockTransport(_handler))
    )
    body = await oauth._token_request(
        "https://slack.com/api/oauth.v2.user.access", {"code_verifier": "v"}
    )
    assert body["access_token"] == "xoxp-1"

    def _refused(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": "invalid_code"})

    monkeypatch.setattr(
        oauth.httpx, "AsyncClient", lambda **kwargs: real(transport=httpx.MockTransport(_refused))
    )
    with pytest.raises(Exception, match="invalid_code"):
        await oauth._token_request("https://slack.com/api/oauth.v2.user.access", {})


def test_secrets_round_trip_and_stay_encrypted(settings: Settings) -> None:
    """Stored tokens are ciphertext and decrypt with the local key."""
    blob = seal(settings, {"access_token": "abc"})
    assert "abc" not in blob
    assert unseal(settings, blob) == {"access_token": "abc"}


def test_custom_server_connects_and_lists_tools(client: TestClient, mcp_url: str) -> None:
    """A custom MCP server is tested on add; its tools are marked read-only or changing."""
    connector = _connect_custom(client, mcp_url)
    assert connector["status"] == "connected", connector
    tools = {tool["name"]: tool["read_only"] for tool in connector["tools"]}
    assert tools["search_files"] is True
    assert tools["create_file"] is False
    assert TOKEN not in str(connector)


def test_wrong_token_is_reported(client: TestClient, mcp_url: str) -> None:
    """A refused token leaves the connector in error with a plain message."""
    connector = _connect_custom(client, mcp_url, token="wrong")
    assert connector["status"] == "error"
    assert "refused the credentials" in connector["error"]


def test_connector_requests_route_without_the_model() -> None:
    """Moving files or messages through a named tool is a fixed route."""
    assert product_lock("Save the report deck to Google Drive") == "use_connector"
    assert product_lock("Post the key takeaways to #research") == "use_connector"
    assert product_lock("Import the study brief from Google Drive") == "use_connector"
    assert product_lock("Add a question asking whether they share files via Google Drive") is None
    assert (
        product_lock("Run a key driver analysis to find what helps to drive recommendation") is None
    )


def test_agent_imports_a_brief_and_queues_an_upload(client: TestClient, mcp_url: str) -> None:
    """Reads run at once and save to the project; an upload waits for approval, then runs."""
    connector = _connect_custom(client, mcp_url)
    project = create_project(client, "Connector study")
    rounds: list[ConnectorPlan] = [
        ConnectorPlan(
            calls=[
                PlannedCall(
                    connector_id=connector["id"],
                    tool="read_file",
                    arguments_json='{"file_id": "f-brief"}',
                    purpose="Read the BrewCo brief",
                    save_as="BrewCo study brief.md",
                )
            ]
        ),
        ConnectorPlan(done=True, reply="I imported the BrewCo brief."),
    ]

    async def _plan(*_args: object, **_kwargs: object) -> ConnectorPlan:
        return rounds.pop(0)

    with patch("app.connectors.agent.run_structured", _plan):
        sent = client.post(
            f"/api/conversations/{project['conversation_id']}/messages",
            json={"content": "Import the study brief from Google Drive"},
        )
    assert sent.status_code == 201, sent.text
    messages = client.get(f"/api/conversations/{project['conversation_id']}/messages").json()
    reply = messages[-1]["content"]
    assert "Saved BrewCo_study_brief.md to the project." in reply

    upload_id = _upload_text(client, project["id"])
    rounds[:] = [
        ConnectorPlan(
            calls=[
                PlannedCall(
                    connector_id=connector["id"],
                    tool="create_file",
                    arguments_json=(
                        '{"name": "$file_name:%s", "content_base64": "$file:%s", "parent_id": "f-reports"}'
                        % (upload_id, upload_id)
                    ),
                    purpose="Upload notes.txt to the Reports folder",
                )
            ]
        )
    ]
    with patch("app.connectors.agent.run_structured", _plan):
        client.post(
            f"/api/conversations/{project['conversation_id']}/messages",
            json={"content": "Save the notes to Google Drive in Reports"},
        )
    actions = client.get(f"/api/projects/{project['id']}/connector-actions").json()
    pending = [item for item in actions if item["status"] == "pending"]
    assert len(pending) == 1
    assert pending[0]["arguments"]["content_base64"] == f"$file:{upload_id}"
    assert pending[0]["display"]["content_base64"] == "contents of notes.txt"
    assert pending[0]["display"]["name"] == "notes.txt"
    before = len(STATE["files"])
    done = client.post(f"/api/connector-actions/{pending[0]['id']}/approve").json()
    assert done["status"] == "done", done
    assert len(STATE["files"]) == before + 1
    created = [item for item in STATE["files"].values() if item["name"] == "notes.txt"]
    assert created and created[0]["size"] == len(b"Field closes Friday.")
    again = client.post(f"/api/connector-actions/{pending[0]['id']}/approve")
    assert again.status_code == 400
    last = client.get(f"/api/conversations/{project['conversation_id']}/messages").json()[-1]
    assert "Link: https://drive.example/" in last["content"]


def test_cancelled_action_does_not_run(client: TestClient, mcp_url: str) -> None:
    """Cancelling leaves the remote tool untouched."""
    connector = _connect_custom(client, mcp_url)
    project = create_project(client, "Cancel study")
    plan = ConnectorPlan(
        calls=[
            PlannedCall(
                connector_id=connector["id"],
                tool="post_message",
                arguments_json='{"channel_id": "C01", "text": "Topline is ready."}',
                purpose="Post to #research",
            )
        ]
    )

    async def _plan(*_args: object, **_kwargs: object) -> ConnectorPlan:
        return plan

    with patch("app.connectors.agent.run_structured", _plan):
        client.post(
            f"/api/conversations/{project['conversation_id']}/messages",
            json={"content": "Post the topline to #research"},
        )
    action = client.get(f"/api/projects/{project['id']}/connector-actions").json()[0]
    before = len(STATE["messages"])
    cancelled = client.post(f"/api/connector-actions/{action['id']}/cancel").json()
    assert cancelled["status"] == "cancelled"
    assert len(STATE["messages"]) == before


def test_no_connectors_explains_where_to_connect(client: TestClient) -> None:
    """Without a connected tool the agent points to Connectors and calls no model."""
    project = create_project(client, "Unconnected")
    client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": "Save the report deck to Google Drive"},
    )
    reply = client.get(f"/api/conversations/{project['conversation_id']}/messages").json()[-1]
    assert "No connectors are connected yet" in reply["content"]


def _upload_text(client: TestClient, project_id: str) -> str:
    """Upload a small text file.

    Args:
        client: Test client.
        project_id: Project id.

    Returns:
        File id.
    """
    response = client.post(
        f"/api/projects/{project_id}/files",
        files={"file": ("notes.txt", b"Field closes Friday.", "text/plain")},
    )
    assert response.status_code == 201, response.text
    return response.json()["file_id"]


def test_readable_result_prefers_name_and_link() -> None:
    """JSON answers become a name and a link; plain text passes through."""
    from app.connectors.agent import readable_result

    shown = readable_result('{"name": "deck.pptx", "webViewLink": "https://x/1"}')
    assert shown == "deck.pptx\nLink: https://x/1"
    assert readable_result('{"ok": true, "ts": "1"}') == "The tool confirmed it."
    assert readable_result("Posted.") == "Posted."
