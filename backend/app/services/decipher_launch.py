"""Upload a programmed survey.xml to Forsta Decipher."""

import re
from typing import Protocol
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field

from app.config import Settings
from app.engines.decipher_repair import XmlRepair, repair_survey_xml
from app.errors import AppError
from app.services.decipher_errors import error_detail, error_messages, scrub

_DEFAULT_BASE = "https://selfserve.decipherinc.com/api/v1"
_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]*$")
_COMPANY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
# One upload plus three repairs. A change that Decipher still rejects stops the loop.
_UPLOAD_ATTEMPTS = 4


class LaunchResult(BaseModel):
    """Outcome of sending survey XML to Decipher."""

    launched: bool
    message: str
    survey_path: str | None = None
    survey_url: str | None = None
    xml: str = ""
    fixes: list[str] = Field(default_factory=list)


class DecipherRequestError(AppError):
    """Decipher refused the call or could not be reached.

    Args:
        message: Actionable explanation safe to show in the UI.
        code: Stable machine-readable error code.
        survey_path: Survey path already created, when one exists.
        survey_url: Public survey address for that path.
        decipher_status: HTTP status Decipher returned. Zero when the host was not reached.
        errors: Validation messages from the response body.
    """

    def __init__(
        self,
        message: str,
        code: str,
        survey_path: str | None = None,
        survey_url: str | None = None,
        decipher_status: int = 0,
        errors: list[str] | None = None,
    ) -> None:
        super().__init__(message, code)
        self.survey_path = survey_path
        self.survey_url = survey_url
        self.decipher_status = decipher_status
        self.errors = errors or []
        self.xml: str | None = None
        self.fixes: list[str] = []


class SurveyLauncher(Protocol):
    """Uploads a programmed survey."""

    def launch(self, xml: str, name: str, survey_path: str | None = None) -> LaunchResult:
        """Send survey XML to Decipher.

        Args:
            xml: Survey document.
            name: Survey name.
            survey_path: Existing Decipher path to update. A new survey is created when omitted.

        Returns:
            Launch result.
        """
        ...


class NotConfiguredLauncher:
    """Refuses to launch because no API key is configured."""

    def launch(self, xml: str, name: str, survey_path: str | None = None) -> LaunchResult:
        """Refuse a launch.

        Args:
            xml: Survey document. It is not transmitted.
            name: Survey name.
            survey_path: Ignored. Nothing is updated.

        Returns:
            This method does not return.

        Raises:
            AppError: Direct launch is not configured.
        """
        del xml, name, survey_path
        raise AppError(
            "Decipher API is not configured. Download the XML and import it in Decipher.",
            "decipher_not_configured",
        )


class DecipherClient:
    """Creates or updates a Selfserve survey and uploads survey.xml."""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        """Store credentials and an optional transport.

        Args:
            settings: Application settings. The API key stays on this object.
            transport: HTTP transport. Tests pass a mock so no request leaves the process.
        """
        self.settings = settings
        self.transport = transport

    def launch(self, xml: str, name: str, survey_path: str | None = None) -> LaunchResult:
        """Create a survey when needed, then replace its survey.xml.

        Args:
            xml: Survey document.
            name: Name shown in Research Hub.
            survey_path: Existing path to update.

        Returns:
            Path, public URL, and the XML Decipher accepted. That XML includes a
            correction when the first upload was rejected for a structure error.

        Raises:
            DecipherRequestError: The base URL is invalid, Decipher rejects the call, or the host cannot be reached.
        """
        base = _api_base(self.settings.decipher_api_base)
        key = self.settings.decipher_api_key.strip()
        company = _company(self.settings.decipher_company)
        path = _clean_path(survey_path)
        headers = {"x-apikey": key, "Accept": "application/json"}
        try:
            with httpx.Client(
                transport=self.transport,
                timeout=60.0,
                follow_redirects=False,
                headers=headers,
            ) as client:
                if path is None:
                    path = _create_survey(client, base, company, name, key)
                accepted, fixes = _upload_until_accepted(client, base, path, xml, key)
        except httpx.HTTPError as exc:
            raise DecipherRequestError(
                "Decipher could not be reached. The XML is still saved for download.",
                "decipher_unavailable",
                survey_path=path,
                survey_url=_public_url(base, path) if path else None,
            ) from exc
        public = _public_url(base, path)
        return LaunchResult(
            launched=True,
            message=_uploaded_message(path, fixes),
            survey_path=path,
            survey_url=public,
            xml=accepted,
            fixes=fixes,
        )


def launcher_from_settings(
    settings: Settings, transport: httpx.BaseTransport | None = None
) -> SurveyLauncher:
    """Return a live client when an API key is set.

    A blank key does not open a connection. ``DECIPHER_API_BASE`` defaults to
    the Selfserve ``/api/v1`` URL, and ``DECIPHER_COMPANY`` defaults to ``self``.

    Args:
        settings: Application settings.
        transport: Optional HTTP transport for tests.

    Returns:
        Configured client, or the not-configured launcher.
    """
    if not settings.decipher_api_key.strip():
        return NotConfiguredLauncher()
    return DecipherClient(settings, transport=transport)


def _api_base(raw: str) -> str:
    """Return the API root, using Selfserve when the setting is blank.

    Args:
        raw: Configured base URL.

    Returns:
        HTTPS URL ending in ``/api/v1`` with no trailing slash.

    Raises:
        DecipherRequestError: The URL is not HTTPS or does not end in ``/api/v1``.
    """
    base = raw.strip().rstrip("/") or _DEFAULT_BASE
    if not base.startswith("https://") or not base.endswith("/api/v1"):
        raise DecipherRequestError(
            "DECIPHER_API_BASE must be an https URL ending in /api/v1.",
            "decipher_not_configured",
        )
    return base


def _company(raw: str) -> str:
    """Return the company segment used in the create URL.

    Args:
        raw: Configured company id or name.

    Returns:
        ``self`` when blank, otherwise the given company.

    Raises:
        DecipherRequestError: The company contains characters that cannot go in a URL path.
    """
    company = raw.strip() or "self"
    if _COMPANY.fullmatch(company) is None:
        raise DecipherRequestError(
            "DECIPHER_COMPANY may contain only letters, numbers, dots, hyphens, and underscores.",
            "decipher_not_configured",
        )
    return company


def _clean_path(value: str | None) -> str | None:
    """Return a survey path that is safe to join onto the API URL.

    Args:
        value: Stored or returned path.

    Returns:
        Path without a leading slash, or None when nothing usable was given.
    """
    if not value or not value.strip():
        return None
    path = value.strip().strip("/")
    parts = path.split("/")
    # Reason: a stored path is placed in the request URL, so parent segments are rejected.
    if not path or ".." in parts or _PATH.fullmatch(path) is None:
        return None
    return path


def _public_url(base: str, path: str) -> str:
    """Build the respondent survey address on the same host, outside ``/api/v1``.

    Args:
        base: API root ending in ``/api/v1``.
        path: Survey path such as ``selfserve/123/456789``.

    Returns:
        Public survey URL. Decipher serves the questionnaire at ``/survey/{path}``.
    """
    host = base.removesuffix("/api/v1")
    # Reason: /selfserve/... is the API path, not a page. The live survey is under /survey/.
    return f"{host}/survey/{path}"


def _create_survey(client: httpx.Client, base: str, company: str, name: str, key: str) -> str:
    """Create a beacon survey and return its path.

    Args:
        client: Open HTTP client.
        base: API root.
        company: Company id or ``self``.
        name: Research Hub name.
        key: API key, used only to scrub error text.

    Returns:
        Survey path such as ``selfserve/123/456789``.

    Raises:
        DecipherRequestError: Decipher did not create a survey or omitted the path.
    """
    title = name.strip()[:200] or "Survey"
    response = client.post(
        f"{base}/rh/companies/{quote(company, safe='')}/surveys",
        json={"name": title, "ptype": "beacon", "lang": "english"},
    )
    body = _json_object(response)
    _raise_for_status(response, body, key, survey_path=None, survey_url=None)
    path = _clean_path(body.get("path") if isinstance(body.get("path"), str) else None)
    if path is None:
        raise DecipherRequestError(
            "Decipher created a survey but did not return its path.",
            "decipher_rejected",
        )
    return path


def _upload_until_accepted(
    client: httpx.Client, base: str, path: str, xml: str, key: str
) -> tuple[str, list[str]]:
    """Upload survey.xml, and correct structure errors Decipher names.

    Args:
        client: Open HTTP client.
        base: API root.
        path: Survey path.
        xml: Survey document from the compiler.
        key: API key, used only to scrub error text.

    Returns:
        The XML Decipher accepted and the corrections that were required.

    Raises:
        DecipherRequestError: Decipher rejected the file and no further safe correction applies.
    """
    current = xml
    fixes: list[str] = []
    last: DecipherRequestError | None = None
    for _ in range(_UPLOAD_ATTEMPTS):
        try:
            _upload_xml(client, base, path, current, key)
        except DecipherRequestError as exc:
            last = exc
            repaired = _repair_rejection(current, exc)
            if repaired is None:
                _remember_attempt(exc, current, fixes)
                raise
            fixes.extend(repaired.fixes)
            current = repaired.xml
            continue
        return current, fixes
    if last is None:
        raise DecipherRequestError(
            "Decipher rejected survey.xml.",
            "decipher_rejected",
            survey_path=path,
            survey_url=_public_url(base, path),
        )
    _remember_attempt(last, current, fixes)
    raise last


def _repair_rejection(xml: str, exc: DecipherRequestError) -> XmlRepair | None:
    """Return a corrected document when this rejection is a structure error.

    Args:
        xml: Document that was just rejected.
        exc: Decipher's rejection.

    Returns:
        A repair whose XML changed, or None when another upload would repeat this one.
    """
    if exc.decipher_status != 400 or not exc.errors:
        return None
    repaired = repair_survey_xml(xml, exc.errors)
    if not repaired.changed:
        return None
    return repaired


def _remember_attempt(exc: DecipherRequestError, xml: str, fixes: list[str]) -> None:
    """Keep the last document and any corrections on the error the caller sees.

    Args:
        exc: Rejection that stopped the uploads.
        xml: Last document sent, including corrections already applied.
        fixes: Corrections applied on earlier attempts.
    """
    exc.xml = xml
    exc.fixes = list(fixes)
    if not fixes:
        return
    detail = f"Corrected before the last attempt: {'; '.join(fixes)}"
    if detail not in exc.message:
        exc.message = f"{exc.message} {detail}"


def _uploaded_message(path: str, fixes: list[str]) -> str:
    """Describe a successful upload, including corrections Decipher asked for.

    Args:
        path: Survey path.
        fixes: Corrections applied before the accepted upload.

    Returns:
        User-facing sentence.
    """
    uploaded = f"Uploaded to Decipher at {path}."
    if not fixes:
        return uploaded
    noun = "issue" if len(fixes) == 1 else "issues"
    return (
        f"{uploaded} Corrected {len(fixes)} Decipher {noun} and uploaded again: {'; '.join(fixes)}"
    )


def _upload_xml(client: httpx.Client, base: str, path: str, xml: str, key: str) -> None:
    """Replace survey.xml and ask Decipher to validate it before saving.

    Args:
        client: Open HTTP client.
        base: API root.
        path: Survey path.
        xml: Survey document.
        key: API key, used only to scrub error text.

    Raises:
        DecipherRequestError: Decipher rejected the file or the survey is not editable.
    """
    response = client.put(
        f"{base}/surveys/{path}/files/survey.xml",
        files={"contents": ("survey.xml", xml.encode("utf-8"), "application/xml")},
        data={"validate": "true", "overwriteLive": "false", "location": "root"},
    )
    body = _json_object(response)
    _raise_for_status(response, body, key, survey_path=path, survey_url=_public_url(base, path))


def _json_object(response: httpx.Response) -> dict:
    """Read a JSON object from a response.

    Args:
        response: Decipher response.

    Returns:
        Object body, or an empty object when the body is not a JSON object.
    """
    try:
        payload = response.json()
    except ValueError:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _raise_for_status(
    response: httpx.Response,
    body: dict,
    key: str,
    survey_path: str | None,
    survey_url: str | None,
) -> None:
    """Turn a failed Decipher response into an application error.

    Args:
        response: Decipher response.
        body: Parsed JSON object.
        key: API key to remove if the body echoes it.
        survey_path: Path to keep so a retry updates the same survey.
        survey_url: Public URL for that path.

    Raises:
        DecipherRequestError: The status is not a success.
    """
    if response.is_success:
        return
    detail = error_detail(body)
    if response.status_code == 401:
        message = "Decipher rejected the API key. Check DECIPHER_API_KEY in backend/.env."
    elif response.status_code == 403:
        message = "Decipher refused this API key for that survey."
    elif response.status_code == 404:
        message = "Decipher could not find that survey."
    elif response.status_code == 400:
        message = "Decipher rejected survey.xml."
    else:
        message = f"Decipher returned HTTP {response.status_code}."
    if detail:
        message = f"{message} {detail}"
    raise DecipherRequestError(
        scrub(message, key),
        "decipher_rejected",
        survey_path=survey_path,
        survey_url=survey_url,
        decipher_status=response.status_code,
        errors=[scrub(item, key) for item in error_messages(body)],
    )
