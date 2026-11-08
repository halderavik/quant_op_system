"""Reserved Decipher launch boundary. No request is sent to Forsta."""

from typing import Protocol

from pydantic import BaseModel

from app.config import Settings
from app.errors import AppError


class LaunchResult(BaseModel):
    """Outcome of a future direct launch."""

    launched: bool
    message: str


class SurveyLauncher(Protocol):
    """Uploads a programmed survey. The live client is not implemented."""

    def launch(self, xml: str, name: str) -> LaunchResult:
        """Send survey XML to Decipher.

        Args:
            xml: Survey document.
            name: Survey name.

        Returns:
            Launch result.
        """
        ...


class NotConfiguredLauncher:
    """Refuses to launch because no Forsta client is connected."""

    def launch(self, xml: str, name: str) -> LaunchResult:
        """Refuse a launch.

        Args:
            xml: Survey document. It is not transmitted.
            name: Survey name.

        Returns:
            This method does not return.

        Raises:
            AppError: Direct launch is not configured.
        """
        del xml, name
        raise AppError(
            "Decipher API is not configured. Download the XML and import it in Decipher.",
            "decipher_not_configured",
        )


def launcher_from_settings(settings: Settings) -> SurveyLauncher:
    """Return the launcher. A live Forsta client is not implemented.

    ``DECIPHER_API_BASE``, ``DECIPHER_API_KEY``, and ``DECIPHER_COMPANY`` are
    reserved for that client. This function does not read them into a request.

    Args:
        settings: Application settings.

    Returns:
        Not-configured launcher.
    """
    _reserved = (
        settings.decipher_api_base,
        settings.decipher_api_key,
        settings.decipher_company,
    )
    del _reserved
    return NotConfiguredLauncher()
