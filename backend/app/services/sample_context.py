"""Workspace, duration, and money helpers shared by a quote and a launch."""

from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import AppError
from app.repositories.records import ArtifactRepository
from app.schemas.questionnaire import Questionnaire
from app.services.prolific_client import ProlificClient

_CURRENCIES = {"USD", "GBP"}


def _workspace(client: ProlificClient, settings: Settings) -> tuple[str, str, dict]:
    """Resolve the workspace, its currency, and its balance.

    Args:
        client: Prolific client.
        settings: Application settings.

    Returns:
        Workspace id, currency, and balance.

    Raises:
        AppError: Several workspaces exist and none was configured, or the currency is unsupported.
    """
    workspace_id = settings.prolific_workspace_id.strip()
    if not workspace_id:
        workspaces = client.list_workspaces()
        if not workspaces:
            raise AppError("This Prolific account has no workspace.", "prolific_workspace_required")
        if len(workspaces) != 1:
            names = ", ".join(str(item.get("title") or item.get("id")) for item in workspaces)
            raise AppError(
                f"This account has more than one Prolific workspace ({names}). "
                "Set PROLIFIC_WORKSPACE_ID.",
                "prolific_workspace_required",
            )
        workspace_id = str(workspaces[0]["id"])
    balance = client.workspace_balance(workspace_id)
    currency = str(balance.get("currency_code") or "").upper()
    if currency not in _CURRENCIES:
        shown = currency or "an unknown currency"
        raise AppError(
            f"Prolific reward recommendations support USD and GBP. This workspace uses {shown}.",
            "prolific_rejected",
        )
    return workspace_id, currency, balance


def _project_id(client: ProlificClient, settings: Settings, workspace_id: str) -> str | None:
    """Return the configured project, or the first project in the workspace.

    Args:
        client: Prolific client.
        settings: Application settings.
        workspace_id: Workspace id.

    Returns:
        Project id, or None when the workspace has no project yet.
    """
    configured = settings.prolific_project_id.strip()
    if configured:
        return configured
    projects = client.list_projects(workspace_id)
    if not projects:
        return None
    return str(projects[0].get("id") or "") or None


def _minutes(stated: int | None, question_count: int) -> tuple[int, bool]:
    """Choose the estimated minutes.

    Args:
        stated: Minutes the user wrote.
        question_count: Questions on the questionnaire.

    Returns:
        Minutes, and whether they were estimated.

    Raises:
        AppError: Neither the user nor a questionnaire supplies a duration.
    """
    if stated is not None and stated > 0:
        return stated, False
    if question_count > 0:
        return question_count, True
    raise AppError(
        "How many minutes will the survey take?",
        "clarification_needed",
    )


def _study_context(db: Session, project_id: str) -> tuple[str, list[str], int, str | None]:
    """Read the questionnaire title and the uploaded Decipher URL.

    Args:
        db: Session.
        project_id: Project id.

    Returns:
        Title, sample notes, question count, and survey URL.
    """
    artifacts = ArtifactRepository(db)
    title = "Survey"
    notes: list[str] = []
    question_count = 0
    questionnaire = artifacts.latest_of_type(project_id, "questionnaire")
    if questionnaire is not None:
        document = Questionnaire.model_validate(questionnaire.content)
        title = document.title or title
        notes = list(document.sample_notes)
        question_count = len(document.questions)
    survey_url = None
    decipher = artifacts.latest_of_type(project_id, "decipher_survey")
    if decipher is not None and isinstance(decipher.content, dict):
        url = decipher.content.get("survey_url")
        if isinstance(url, str) and url.strip():
            survey_url = url.strip()
    return title, notes, question_count, survey_url


def _money(cents: int, currency: str) -> str:
    """Format a subcurrency amount.

    Args:
        cents: Amount in cents or pence.
        currency: ISO currency.

    Returns:
        Display amount.
    """
    amount = cents / 100
    symbol = {"GBP": "£", "USD": "$"}.get(currency, "")
    if symbol:
        return f"{symbol}{amount:,.2f}"
    return f"{amount:,.2f} {currency}"


def _require_key(settings: Settings) -> None:
    """Refuse to call Prolific when the token is blank.

    Args:
        settings: Application settings.

    Raises:
        AppError: No token is configured.
    """
    if not settings.prolific_configured:
        raise AppError(
            "Prolific API is not configured. Add PROLIFIC_API_KEY to backend/.env and restart.",
            "prolific_not_configured",
        )
