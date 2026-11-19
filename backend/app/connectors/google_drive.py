"""Google Drive through Google's standard Drive API, served as an MCP server by this backend.

Google's own Drive MCP server is only open to Google Workspace accounts in its
Developer Preview. This server gives any Google account, including a personal Gmail
account, the same connector: the connector agent calls these tools over MCP like any
other server, and each call goes to the Drive API with the signed-in user's own token.
Nothing is stored here; the token arrives on each request and is never logged.
"""

import base64
import json
import uuid
from typing import Any
from urllib.parse import urlparse

import httpx
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import BlobResourceContents, EmbeddedResource, TextContent, ToolAnnotations

DRIVE_API = "https://www.googleapis.com/drive/v3"
UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"
MOUNT_PATH = "/api/builtin/google-drive"
MAX_BYTES = 25 * 1024 * 1024
FOLDER = "application/vnd.google-apps.folder"
_FIELDS = "id,name,mimeType,modifiedTime,size,webViewLink,parents"
# Google files have no bytes of their own; they are exported to the matching Office format.
EXPORTS = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
}

READ = ToolAnnotations(read_only_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False)


class DriveError(ToolError):
    """A Drive API failure, worded for the researcher.

    A ToolError's message reaches the caller; any other exception is reported only as
    "Error executing tool".
    """


def _quote(text: str) -> str:
    """Escape a value for a Drive search query, which uses single-quoted strings."""
    return text.replace("\\", "\\\\").replace("'", "\\'")


def _token(ctx: Context) -> str:
    header = (ctx.headers or {}).get("authorization", "")
    if not header.lower().startswith("bearer ") or not header[7:].strip():
        raise DriveError("Google Drive is not signed in. Connect it under Connectors.")
    return header[7:].strip()


def _check(response: httpx.Response) -> httpx.Response:
    """Raise a readable error for a failed Drive call."""
    if response.is_success:
        return response
    try:
        detail = response.json().get("error", {}).get("message", "")
    except ValueError:
        detail = ""
    if response.status_code == 401:
        raise DriveError("Google refused the sign-in. Reconnect Google Drive under Connectors.")
    if response.status_code == 403:
        raise DriveError(
            "Google Drive did not allow that. Check the Drive API is enabled for the project "
            f"and the account can open the file. {detail}".strip()
        )
    if response.status_code == 404:
        raise DriveError("That file or folder was not found in Google Drive.")
    raise DriveError(f"Google Drive returned an error ({response.status_code}). {detail}".strip())


def _summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "folder": item.get("mimeType") == FOLDER,
        "type": item.get("mimeType"),
        "modified": item.get("modifiedTime"),
        "link": item.get("webViewLink"),
    }


def build_server(transport: httpx.AsyncBaseTransport | None = None) -> MCPServer:
    """Create the Drive MCP server.

    Args:
        transport: HTTP transport for the Drive API. Tests pass a mock; None uses the network.

    Returns:
        MCP server with search, read, create-folder, and upload tools.
    """
    server = MCPServer(
        "Google Drive",
        instructions="Search, read, and save files in the signed-in user's Google Drive.",
    )

    def http(ctx: Context) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=transport,
            timeout=60,
            headers={"Authorization": f"Bearer {_token(ctx)}"},
        )

    @server.tool(
        annotations=READ,
        description=(
            "Search Google Drive for files and folders by name or text. Leave query empty to list "
            "recent files. Give folder_id to list or search inside one folder. Returns id, name, "
            "whether it is a folder, type, modified time, and link."
        ),
    )
    async def search_files(
        ctx: Context, query: str = "", folder_id: str = "", limit: int = 25
    ) -> str:
        terms = ["trashed = false"]
        if query.strip():
            text = _quote(query.strip())
            terms.append(f"(name contains '{text}' or fullText contains '{text}')")
        if folder_id.strip():
            terms.append(f"'{_quote(folder_id.strip())}' in parents")
        params = {
            "q": " and ".join(terms),
            "fields": f"files({_FIELDS})",
            "pageSize": str(max(1, min(int(limit), 100))),
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if not query.strip():
            params["orderBy"] = "modifiedTime desc"
        async with http(ctx) as client:
            response = _check(await client.get(f"{DRIVE_API}/files", params=params))
        return json.dumps([_summary(item) for item in response.json().get("files", [])])

    @server.tool(
        annotations=READ,
        description=(
            "Download one Google Drive file by id so it can be saved into the project. Google Docs "
            "come back as .docx, Sheets as .xlsx, and Slides as .pptx; other files as they are."
        ),
    )
    async def read_file(ctx: Context, file_id: str) -> list[TextContent | EmbeddedResource]:
        async with http(ctx) as client:
            meta = _check(
                await client.get(
                    f"{DRIVE_API}/files/{file_id}",
                    params={"fields": _FIELDS, "supportsAllDrives": "true"},
                )
            ).json()
            kind = meta.get("mimeType", "")
            name = str(meta.get("name") or file_id)
            if kind == FOLDER:
                raise DriveError(f"{name} is a folder. Search inside it with folder_id instead.")
            if kind in EXPORTS:
                media, suffix = EXPORTS[kind]
                response = await client.get(
                    f"{DRIVE_API}/files/{file_id}/export", params={"mimeType": media}
                )
                if not name.lower().endswith(suffix):
                    name += suffix
            elif kind.startswith("application/vnd.google-apps."):
                raise DriveError(f"{name} is a Google file type that cannot be downloaded.")
            else:
                if int(meta.get("size") or 0) > MAX_BYTES:
                    raise DriveError(f"{name} is larger than 25 MB, so it was not downloaded.")
                media = kind or "application/octet-stream"
                response = await client.get(
                    f"{DRIVE_API}/files/{file_id}",
                    params={"alt": "media", "supportsAllDrives": "true"},
                )
            data = _check(response).content
        if len(data) > MAX_BYTES:
            raise DriveError(f"{name} is larger than 25 MB, so it was not downloaded.")
        safe = name.replace("/", "_")
        return [
            TextContent(type="text", text=f"Downloaded {name} ({len(data)} bytes)."),
            EmbeddedResource(
                type="resource",
                resource=BlobResourceContents(
                    uri=f"gdrive://{file_id}/{safe}",
                    mime_type=media,
                    blob=base64.b64encode(data).decode(),
                ),
            ),
        ]

    @server.tool(
        annotations=WRITE,
        description="Create a folder in Google Drive, inside parent_id when given. Returns its id and link.",
    )
    async def create_folder(ctx: Context, name: str, parent_id: str = "") -> str:
        body: dict[str, Any] = {"name": name, "mimeType": FOLDER}
        if parent_id.strip():
            body["parents"] = [parent_id.strip()]
        async with http(ctx) as client:
            response = _check(
                await client.post(
                    f"{DRIVE_API}/files",
                    params={"fields": _FIELDS, "supportsAllDrives": "true"},
                    json=body,
                )
            )
        return json.dumps(_summary(response.json()))

    @server.tool(
        annotations=WRITE,
        description=(
            "Upload a file to Google Drive from base64 content, inside the folder parent_id when "
            "given. Returns the new file's id, name, and link."
        ),
    )
    async def create_file(
        ctx: Context, name: str, content_base64: str, mime_type: str = "", parent_id: str = ""
    ) -> str:
        data = base64.b64decode(content_base64)
        if len(data) > MAX_BYTES:
            raise DriveError(f"{name} is larger than 25 MB, so it was not uploaded.")
        meta: dict[str, Any] = {"name": name}
        if parent_id.strip():
            meta["parents"] = [parent_id.strip()]
        media = mime_type or "application/octet-stream"
        boundary = f"qos-{uuid.uuid4().hex}"
        body = (
            (
                f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
                f"{json.dumps(meta)}\r\n--{boundary}\r\nContent-Type: {media}\r\n\r\n"
            ).encode()
            + data
            + f"\r\n--{boundary}--\r\n".encode()
        )
        async with http(ctx) as client:
            response = _check(
                await client.post(
                    f"{UPLOAD_API}/files",
                    params={
                        "uploadType": "multipart",
                        "fields": _FIELDS,
                        "supportsAllDrives": "true",
                    },
                    content=body,
                    headers={"Content-Type": f"multipart/related; boundary={boundary}"},
                )
            )
        result = _summary(response.json())
        result["size"] = len(data)
        return json.dumps(result)

    return server


def http_app(server: MCPServer, public_base_url: str) -> Any:
    """Return the server's streamable HTTP app, accepting this backend's own host name.

    Args:
        server: Drive MCP server.
        public_base_url: The backend's public URL; its host is allowed alongside localhost.

    Returns:
        ASGI app serving MCP at ``/mcp``.
    """
    host = urlparse(public_base_url).netloc
    allowed = ["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*", "[::1]:*"]
    if host and host not in allowed:
        allowed.append(host)
    return server.streamable_http_app(
        stateless_http=True,
        max_request_body_size=40 * 1024 * 1024,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=allowed
        ),
    )
