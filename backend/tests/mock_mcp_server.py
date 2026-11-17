"""A stand-in MCP server shaped like Google Drive and Slack, for tests and rehearsals.

Run it with ``python -m tests.mock_mcp_server --port 8765 --token demo-token`` from
``backend/``, then add ``http://127.0.0.1:8765/mcp`` as a custom connector.
"""

import argparse
import base64
import json
import threading
import time
from pathlib import Path
from typing import Any

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

BRIEF = """Coffee shop brand health study brief

Client: BrewCo. Objective: measure awareness, consideration, and image of BrewCo against
three competitors among US coffee drinkers aged 18-65 who buy coffee out of home weekly.
Sample: n=600, quotas on age and region. Topics: brand funnel, image attributes, likelihood
to recommend, and reasons for recommendation.
"""

# Reason: rehearsals import the same brief the demo runbook uses, when the repo has it.
_DEMO_BRIEF = Path(__file__).resolve().parents[2] / "demo" / "brief.md"
if _DEMO_BRIEF.exists():
    BRIEF = _DEMO_BRIEF.read_text(encoding="utf-8")

STATE: dict[str, Any] = {
    "files": {
        "f-brief": {
            "id": "f-brief",
            "name": "BrewCo study brief.txt",
            "folder": "Briefs",
            "text": BRIEF,
        },
        "f-reports": {
            "id": "f-reports",
            "name": "Reports",
            "folder": "",
            "text": "",
            "is_folder": True,
        },
    },
    "messages": [],
}

READ = ToolAnnotations(read_only_hint=True)
WRITE = ToolAnnotations(read_only_hint=False)


def build_server() -> MCPServer:
    """Create the stand-in server with Drive- and Slack-like tools.

    Returns:
        MCP server.
    """
    server = MCPServer("Quant OS stand-in workspace")

    @server.tool(annotations=READ, description="Search files and folders by name.")
    def search_files(query: str) -> str:
        words = [word for word in query.lower().split() if word]
        found = [
            {"id": item["id"], "name": item["name"], "folder": item.get("is_folder", False)}
            for item in STATE["files"].values()
            if not words or any(word in item["name"].lower() for word in words)
        ]
        return json.dumps(found)

    @server.tool(annotations=READ, description="Read a text file's content by id.")
    def read_file(file_id: str) -> str:
        item = STATE["files"].get(file_id)
        if item is None:
            raise ValueError("No such file.")
        return item["text"]

    @server.tool(
        annotations=WRITE,
        description="Create a file from base64 content inside a folder. Returns its id and link.",
    )
    def create_file(
        name: str, content_base64: str, mime_type: str = "", parent_id: str = ""
    ) -> str:
        data = base64.b64decode(content_base64)
        file_id = f"f-{len(STATE['files']) + 1}"
        STATE["files"][file_id] = {
            "id": file_id,
            "name": name,
            "folder": parent_id,
            "text": "",
            "size": len(data),
            "mime_type": mime_type,
        }
        return json.dumps(
            {
                "id": file_id,
                "name": name,
                "size": len(data),
                "link": f"https://drive.example/{file_id}",
            }
        )

    @server.tool(annotations=READ, description="List Slack channels.")
    def list_channels() -> str:
        return json.dumps(
            [{"id": "C01", "name": "research"}, {"id": "C02", "name": "brewco-client"}]
        )

    @server.tool(annotations=WRITE, description="Post a message to a Slack channel by id.")
    def post_message(channel_id: str, text: str) -> str:
        STATE["messages"].append({"channel_id": channel_id, "text": text})
        return json.dumps({"ok": True, "channel": channel_id, "ts": str(time.time())})

    return server


class _BearerGate:
    """Refuse requests without the expected bearer token."""

    def __init__(self, app: Any, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and self.token:
            headers = dict(scope.get("headers") or [])
            if headers.get(b"authorization", b"").decode() != f"Bearer {self.token}":
                await send({"type": "http.response.start", "status": 401, "headers": []})
                await send({"type": "http.response.body", "body": b"unauthorized"})
                return
        await self.app(scope, receive, send)


def app(token: str = "") -> Any:
    """Return the ASGI app.

    Args:
        token: Required bearer token. Empty allows anyone.

    Returns:
        ASGI app serving MCP at /mcp.
    """
    return _BearerGate(
        build_server().streamable_http_app(
            stateless_http=True, max_request_body_size=50 * 1024 * 1024
        ),
        token,
    )


def serve_in_thread(port: int, token: str) -> uvicorn.Server:
    """Start the server on a background thread.

    Args:
        port: Port.
        token: Required bearer token.

    Returns:
        The uvicorn server. Set ``should_exit`` to stop it.
    """
    server = uvicorn.Server(
        uvicorn.Config(app(token), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", default="demo-token")
    args = parser.parse_args()
    uvicorn.run(app(args.token), host="127.0.0.1", port=args.port)
