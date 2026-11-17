"""Ready-made connectors a researcher can switch on, plus a custom MCP server entry."""

from dataclasses import dataclass, field

from app.config import Settings


@dataclass(frozen=True)
class CatalogEntry:
    """One connector the studio knows how to set up.

    Attributes:
        id: Stable catalog id.
        name: Display name.
        category: Short grouping label.
        description: What a researcher uses it for.
        server_url: Remote MCP endpoint. ``{tenant_id}`` is filled from settings.
        auth: ``oauth`` (sign in with the provider) or ``token`` (URL plus optional bearer token).
        scopes: OAuth scopes requested at sign-in.
        authorize_url: Fallback authorization endpoint when discovery fails.
        token_url: Fallback token endpoint when discovery fails.
        extra_authorize: Extra query parameters for the authorization request.
        client_env: Names of the env settings holding the OAuth client id and secret.
        status_note: Availability caveat shown on the card.
        setup: Admin setup steps shown on the card.
        examples: Chat prompts that use the connector.
        docs_url: Provider documentation.
    """

    id: str
    name: str
    category: str
    description: str
    server_url: str
    auth: str
    scopes: tuple[str, ...] = ()
    authorize_url: str = ""
    token_url: str = ""
    extra_authorize: dict[str, str] = field(default_factory=dict)
    client_env: tuple[str, str] = ("", "")
    status_note: str = ""
    setup: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    docs_url: str = ""


CATALOG: tuple[CatalogEntry, ...] = (
    CatalogEntry(
        id="google_drive",
        name="Google Drive",
        category="Files",
        description=(
            "Pull a study brief, questionnaire, or data file from Drive into the project, "
            "and save finished decks, tab books, and questionnaires back to Drive."
        ),
        server_url="https://drivemcp.googleapis.com/mcp/v1",
        auth="oauth",
        scopes=(
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/drive.file",
        ),
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        extra_authorize={"access_type": "offline", "prompt": "consent"},
        client_env=("GOOGLE_MCP_CLIENT_ID", "GOOGLE_MCP_CLIENT_SECRET"),
        status_note="Google's Drive MCP server is in Developer Preview.",
        setup=(
            "Enroll the Google Workspace domain in the Workspace Developer Preview Program.",
            "In Google Cloud, create a project and enable the Google Drive MCP API (drivemcp.googleapis.com).",
            "Configure the OAuth consent screen, then create an OAuth client of type Web application "
            "and select 'Use this client for an AI-powered agent'.",
            "Add the redirect URI shown below to the client.",
            "Put the client id and secret in backend/.env as GOOGLE_MCP_CLIENT_ID and "
            "GOOGLE_MCP_CLIENT_SECRET, then restart the backend.",
        ),
        examples=(
            "Import the study brief from Google Drive",
            "Save the report deck to Google Drive",
        ),
        docs_url="https://developers.google.com/workspace/drive/api/guides/configure-mcp-server",
    ),
    CatalogEntry(
        id="slack",
        name="Slack",
        category="Messaging",
        description=(
            "Post report headlines, field updates, and deliverable links to a project channel, "
            "and read channel threads for client feedback."
        ),
        server_url="https://mcp.slack.com/mcp",
        auth="oauth",
        scopes=(
            "search:read.public",
            "channels:read",
            "channels:history",
            "chat:write",
            "files:read",
            "files:write",
            "users:read",
        ),
        authorize_url="https://slack.com/oauth/v2_user/authorize",
        token_url="https://slack.com/api/oauth.v2.user.access",
        client_env=("SLACK_MCP_CLIENT_ID", "SLACK_MCP_CLIENT_SECRET"),
        status_note="Slack does not allow dynamic client registration, so the workspace needs its own Slack app.",
        setup=(
            "At api.slack.com/apps, create a Slack app for the workspace.",
            "Under Agents & AI Apps, turn on MCP.",
            "Under OAuth & Permissions, add the redirect URL shown below. Slack requires HTTPS, "
            "so set PUBLIC_BASE_URL to an HTTPS address (for example a tunnel) that reaches the backend.",
            "Put the client id and secret in backend/.env as SLACK_MCP_CLIENT_ID and "
            "SLACK_MCP_CLIENT_SECRET, then restart the backend.",
        ),
        examples=(
            "Post the report's key takeaways to #research",
            "Share the tab book in the project Slack channel",
        ),
        docs_url="https://docs.slack.dev/ai/slack-mcp-server/",
    ),
    CatalogEntry(
        id="microsoft_365",
        name="Microsoft 365",
        category="Files",
        description=(
            "Find briefs and data in OneDrive and SharePoint, and save deliverables to a "
            "client SharePoint site."
        ),
        server_url=(
            "https://agent365.svc.cloud.microsoft/agents/tenants/{tenant_id}/servers/mcp_ODSPRemoteServer"
        ),
        auth="oauth",
        scopes=("https://agent365.svc.cloud.microsoft/.default", "offline_access"),
        authorize_url="https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
        client_env=("MICROSOFT_MCP_CLIENT_ID", "MICROSOFT_MCP_CLIENT_SECRET"),
        status_note=(
            "Microsoft's hosted OneDrive and SharePoint server (Agent 365) is in preview and needs a "
            "Microsoft 365 Copilot licence. You can point this card at another Microsoft 365 MCP server instead."
        ),
        setup=(
            "In Microsoft Entra, register an app (web platform) and add the redirect URI shown below.",
            "Grant it the Agent 365 permissions your tenant admin approves, and create a client secret.",
            "Put MICROSOFT_TENANT_ID, MICROSOFT_MCP_CLIENT_ID, and MICROSOFT_MCP_CLIENT_SECRET in "
            "backend/.env, then restart the backend.",
            "To use a different Microsoft 365 MCP server, change the server URL and scopes on this card.",
        ),
        examples=(
            "Find the client brief in SharePoint",
            "Save the tab book to the client SharePoint site",
        ),
        docs_url="https://learn.microsoft.com/microsoft-agent-365/",
    ),
)

CUSTOM = CatalogEntry(
    id="custom",
    name="Custom MCP server",
    category="Other",
    description="Connect any other remote MCP server by URL, with an optional access token.",
    server_url="",
    auth="token",
)


def entry(catalog_id: str) -> CatalogEntry:
    """Return a catalog entry by id.

    Args:
        catalog_id: Catalog id.

    Returns:
        The entry. Unknown ids return the custom entry.
    """
    for item in CATALOG:
        if item.id == catalog_id:
            return item
    return CUSTOM


def client_credentials(settings: Settings, item: CatalogEntry) -> tuple[str, str]:
    """Return the OAuth client id and secret configured for an entry.

    Args:
        settings: Application settings.
        item: Catalog entry.

    Returns:
        Client id and secret. Empty strings when not configured.
    """
    id_env, secret_env = item.client_env
    if not id_env:
        return "", ""
    return (
        str(getattr(settings, id_env.lower(), "") or "").strip(),
        str(getattr(settings, secret_env.lower(), "") or "").strip(),
    )


def fill(template: str, settings: Settings, overrides: dict | None = None) -> str:
    """Fill ``{tenant_id}`` in a URL template.

    Args:
        template: URL template.
        settings: Application settings.
        overrides: Account settings that may carry a tenant id.

    Returns:
        URL with the tenant filled. ``common`` when no tenant is set.
    """
    tenant = str((overrides or {}).get("tenant_id") or settings.microsoft_tenant_id or "common")
    return template.replace("{tenant_id}", tenant)


def redirect_uri(settings: Settings) -> str:
    """Return the OAuth redirect URI providers send the user back to.

    Args:
        settings: Application settings.

    Returns:
        Callback URL on this backend.
    """
    return settings.public_base_url.rstrip("/") + "/api/connectors/oauth/callback"
