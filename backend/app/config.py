"""Runtime configuration loaded from the environment."""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Server-side settings. API keys never leave this process."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    anthropic_api_key: str = ""
    database_url: str = "sqlite:///../data/studio.db"
    storage_root: Path = Path("../data")
    session_db_path: Path = Path("../data/sessions.db")
    # Reason: GPT-6.1 Sol is the fast near-flagship. Astra is stronger and slower.
    model_orchestrator: str = "gpt-6.1-sol"
    model_questionnaire: str = "gpt-6.1-sol"
    model_tabspec: str = "gpt-6.1-sol"
    model_analysis: str = "gpt-6.1-sol"
    model_coding: str = "claude-sonnet-5-5"
    model_validator: str = "gpt-6.1-sol"
    model_general: str = "gpt-6.1-sol"
    model_synthetic: str = "claude-sonnet-5-5"
    model_fallback: str = "gpt-6.1-sol"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    sandbox_image: str = "python:3.12-slim"
    sandbox_timeout_seconds: int = 60
    sandbox_memory_mb: int = 512
    max_upload_mb: float = 200
    openai_tracing_disabled: bool = True
    run_tasks_inline: bool = False
    log_row_text: bool = False
    # Reason: upload runs only when the key is set. The key never leaves this process.
    decipher_api_base: str = "https://selfserve.decipherinc.com/api/v1"
    decipher_api_key: str = ""
    decipher_company: str = "self"
    # Reason: the token is scoped to the researcher account and must not reach the browser.
    prolific_api_base: str = "https://api.prolific.com/api/v1"
    prolific_api_key: str = ""
    prolific_workspace_id: str = ""
    prolific_project_id: str = ""

    @field_validator("storage_root", "session_db_path", mode="before")
    @classmethod
    def _expand_path(cls, value: str | Path) -> Path:
        """Resolve a configured path without requiring it to exist yet.

        Args:
            value: Raw path from the environment.

        Returns:
            Absolute path.
        """
        return Path(value).expanduser().resolve()

    @field_validator("cors_origins")
    @classmethod
    def _cors_not_empty(cls, value: str) -> str:
        """Reject an empty CORS list so the dev UI origin is explicit.

        Args:
            value: Comma-separated origins.

        Returns:
            The original string when it contains at least one origin.
        """
        if not value.strip():
            raise ValueError("CORS_ORIGINS must list at least one origin")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        """Return configured browser origins.

        Returns:
            Origins with surrounding whitespace removed.
        """
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def llm_configured(self) -> bool:
        """Return whether a non-empty API key is configured.

        Returns:
            True when OPENAI_API_KEY is set.
        """
        return bool(self.openai_api_key.strip())

    @property
    def prolific_configured(self) -> bool:
        """Return whether a Prolific token is configured.

        Returns:
            True when PROLIFIC_API_KEY is set.
        """
        return bool(self.prolific_api_key.strip())

    def provider_for(self, model_id: str) -> str:
        """Return which API serves a model id.

        Args:
            model_id: Configured model id.

        Returns:
            ``anthropic`` for Claude ids, otherwise ``openai``.
        """
        if model_id.startswith("claude"):
            return "anthropic"
        return "openai"

    def model_for(self, role: str) -> str:
        """Return the configured model id for an agent role.

        Args:
            role: Role name such as ``questionnaire`` or ``coding``.

        Returns:
            Model id from the environment.
        """
        mapping = {
            "orchestrator": self.model_orchestrator,
            "questionnaire": self.model_questionnaire,
            "tabspec": self.model_tabspec,
            "analysis": self.model_analysis,
            "coding": self.model_coding,
            "validator": self.model_validator,
            "general": self.model_general,
            "synthetic": self.model_synthetic,
        }
        return mapping.get(role, self.model_fallback)


@lru_cache
def get_settings() -> Settings:
    """Load and cache settings for this process.

    Returns:
        Validated settings.
    """
    return Settings()
