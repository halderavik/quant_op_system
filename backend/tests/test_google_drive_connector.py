"""The Google Drive connector served by this backend through the standard Drive API."""

import base64
import json
import socket
import threading
import time
from collections.abc import Iterator

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from app.config import Settings
from app.connectors import client
from app.connectors.agent import _save_import
from app.connectors.catalog import entry, fill
from app.connectors.google_drive import build_server, http_app
from app.services.storage import Storage
from tests.conftest import create_project

GOOGLE_TOKEN = "google-access-token"
DOC = "application/vnd.google-apps.document"
CALLS: list[httpx.Request] = []


def _google(request: httpx.Request) -> httpx.Response:
    """A fake Drive API that records each request."""
    CALLS.append(request)
    if request.headers.get("authorization") != f"Bearer {GOOGLE_TOKEN}":
        return httpx.Response(401, json={"error": {"message": "Invalid Credentials"}})
    path = request.url.path
    if path == "/drive/v3/files" and request.method == "GET":
        return httpx.Response(
            200,
            json={
                "files": [
                    {
                        "id": "doc1",
                        "name": "BrewCo brief",
                        "mimeType": DOC,
                        "webViewLink": "https://docs/doc1",
                    },
                    {
                        "id": "dir1",
                        "name": "Reports",
                        "mimeType": "application/vnd.google-apps.folder",
                    },
                ]
            },
        )
    if path == "/drive/v3/files/doc1" and request.method == "GET":
        return httpx.Response(200, json={"id": "doc1", "name": "BrewCo brief", "mimeType": DOC})
    if path == "/drive/v3/files/doc1/export":
        return httpx.Response(200, content=b"PK-docx-bytes")
    if path == "/drive/v3/files/big" and request.url.params.get("alt") != "media":
        return httpx.Response(
            200,
            json={
                "id": "big",
                "name": "huge.sav",
                "mimeType": "application/octet-stream",
                "size": str(30 * 1024 * 1024),
            },
        )
    if path == "/upload/drive/v3/files":
        return httpx.Response(
            200, json={"id": "new1", "name": "report.pptx", "webViewLink": "https://drive/new1"}
        )
    return httpx.Response(404, json={"error": {"message": "File not found"}})


@pytest.fixture(scope="module")
def drive_url() -> Iterator[str]:
    """Serve the Drive MCP server with the fake Drive API.

    Yields:
        Its MCP endpoint.
    """
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    app = http_app(build_server(httpx.MockTransport(_google)), "http://localhost:8000")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True


async def test_reading_tools_run_at_once_and_writing_tools_need_approval(drive_url: str) -> None:
    """Search and read are read-only; folder creation and upload wait for approval."""
    tools = {tool["name"]: tool for tool in await client.list_tools(drive_url, GOOGLE_TOKEN)}
    assert set(tools) == {"search_files", "read_file", "create_folder", "create_file"}
    assert client.is_read_only(tools["search_files"]) and client.is_read_only(tools["read_file"])
    assert not client.is_read_only(tools["create_folder"])
    assert not client.is_read_only(tools["create_file"])


async def test_search_sends_the_users_token_and_an_escaped_query(drive_url: str) -> None:
    """The signed-in user's token goes to Drive, and quotes in a search are escaped."""
    CALLS.clear()
    outcome = await client.call_tool(
        drive_url, GOOGLE_TOKEN, "search_files", {"query": "BrewCo's brief"}
    )
    assert not outcome.is_error
    found = json.loads(outcome.text)
    assert [item["name"] for item in found] == ["BrewCo brief", "Reports"]
    assert found[1]["folder"] is True
    query = CALLS[-1].url.params["q"]
    assert "name contains 'BrewCo\\'s brief'" in query and "trashed = false" in query


async def test_a_google_doc_comes_back_as_a_word_file(drive_url: str) -> None:
    """A Google Doc is exported as .docx and returned as a file the agent can save."""
    outcome = await client.call_tool(drive_url, GOOGLE_TOKEN, "read_file", {"file_id": "doc1"})
    assert not outcome.is_error
    name, data, media = outcome.files[0]
    assert name == "BrewCo brief.docx"
    assert data == b"PK-docx-bytes"
    assert media.endswith("wordprocessingml.document")


async def test_large_files_are_refused_before_download(drive_url: str) -> None:
    """A file over 25 MB is not downloaded."""
    CALLS.clear()
    outcome = await client.call_tool(drive_url, GOOGLE_TOKEN, "read_file", {"file_id": "big"})
    assert outcome.is_error and "larger than 25 MB" in outcome.text
    assert all(call.url.params.get("alt") != "media" for call in CALLS)


async def test_upload_sends_the_file_into_the_folder(drive_url: str) -> None:
    """An approved upload goes to Drive as a multipart upload inside the chosen folder."""
    CALLS.clear()
    payload = base64.b64encode(b"deck-bytes").decode()
    outcome = await client.call_tool(
        drive_url,
        GOOGLE_TOKEN,
        "create_file",
        {"name": "report.pptx", "content_base64": payload, "parent_id": "dir1"},
    )
    assert not outcome.is_error
    assert json.loads(outcome.text)["link"] == "https://drive/new1"
    upload = CALLS[-1]
    assert upload.url.params["uploadType"] == "multipart"
    body = upload.content
    assert b'"parents": ["dir1"]' in body and b"deck-bytes" in body


async def test_a_refused_sign_in_says_to_reconnect(drive_url: str) -> None:
    """Google's 401 becomes a plain instruction to reconnect."""
    outcome = await client.call_tool(drive_url, "expired", "search_files", {})
    assert outcome.is_error and "Reconnect Google Drive" in outcome.text


def test_catalog_entry_points_at_this_backend(settings: Settings) -> None:
    """The Drive API connector is served from this backend and signs in with Google."""
    item = entry("google_drive_api")
    assert fill(item.server_url, settings) == "http://localhost:8000/api/builtin/google-drive/mcp"
    assert item.client_env == ("GOOGLE_DRIVE_CLIENT_ID", "GOOGLE_DRIVE_CLIENT_SECRET")
    assert "https://www.googleapis.com/auth/drive.file" in item.scopes


def test_the_mounted_server_answers_on_the_backend(client: TestClient) -> None:
    """The backend serves the Drive MCP endpoint, only under its own host name."""
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    path = "/api/builtin/google-drive/mcp"
    response = client.post(path, headers={**headers, "Host": "localhost:8000"}, json=body)
    assert response.status_code == 200, response.text
    assert "search_files" in response.text
    # Reason: another site's page cannot reach the server through a rebound host name.
    refused = client.post(path, headers={**headers, "Host": "evil.example"}, json=body)
    assert refused.status_code == 421


def test_an_import_keeps_the_type_of_the_file_drive_returned(
    client: TestClient, settings: Settings
) -> None:
    """A Word file saved under a planned .md name is stored as .docx."""
    project = create_project(client)
    outcome = _word_outcome()
    session = client.app.state.session_factory()
    try:
        note = _save_import(
            session, Storage(settings), settings, project["id"], "brief.md", outcome
        )
        session.commit()
    finally:
        session.close()
    assert note == "Saved brief.docx to the project."


def _word_outcome():
    """A tool outcome holding a Word file, as read_file returns it."""
    from app.connectors.client import ToolOutcome

    media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return ToolOutcome(
        text="Downloaded BrewCo brief.docx", files=[("BrewCo brief.docx", b"PK-docx", media)]
    )
