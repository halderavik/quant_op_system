"""Prolific HTTP client. The token stays on this object."""

import time
from typing import Any

import httpx

from app.config import Settings
from app.errors import AppError

_NOT_CONFIGURED = (
    "Prolific API is not configured. Add PROLIFIC_API_KEY to backend/.env and restart."
)


class ProlificClient:
    """Calls the researcher API with an injectable transport."""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        """Store the token and an optional transport.

        Args:
            settings: Application settings. The token is not returned to callers.
            transport: HTTP transport. Tests pass a mock so no request leaves the process.
        """
        self.settings = settings
        self.transport = transport
        self.base = settings.prolific_api_base.rstrip("/")
        self.token = settings.prolific_api_key.strip()

    def list_filters(self) -> dict[str, Any]:
        """Return the filter catalog.

        Returns:
            Prolific filter list.
        """
        body = self.request("GET", "/filters/")
        return body if isinstance(body, dict) else {"results": body}

    def eligibility_count(self, filters: list[dict[str, Any]], workspace_id: str) -> int:
        """Count participants who pass every filter.

        Args:
            filters: Prolific filter objects.
            workspace_id: Workspace whose country rules apply.

        Returns:
            Count. Zero means fewer than five participants.
        """
        body = self.request(
            "POST",
            "/eligibility-count/",
            json={"filters": filters, "workspace_id": workspace_id},
        )
        count = body.get("count") if isinstance(body, dict) else None
        if not isinstance(count, int | float):
            raise AppError("Prolific did not return an eligibility count.", "prolific_rejected")
        return int(count)

    def reward_recommendation(self, workspace_id: str, currency: str) -> dict[str, Any]:
        """Return the first hourly reward recommendation.

        Args:
            workspace_id: Workspace id.
            currency: USD or GBP.

        Returns:
            Recommendation object with hourly amounts in cents or pence.
        """
        body = self.request(
            "GET",
            "/reward-recommendations/",
            params={"workspace_id": workspace_id, "currency": currency},
        )
        if isinstance(body, list) and body and isinstance(body[0], dict):
            return body[0]
        raise AppError("Prolific did not return a reward recommendation.", "prolific_rejected")

    def calculate_cost(self, reward_cents: int, places: int, workspace_id: str) -> int:
        """Return the total cost in the workspace subcurrency.

        Args:
            reward_cents: Reward for one completion.
            places: Completed places to price.
            workspace_id: Workspace whose fees and VAT apply.

        Returns:
            Total including fees and VAT.
        """
        body = self.request(
            "POST",
            "/study-cost-calculator/",
            json={
                "reward": reward_cents,
                "total_available_places": places,
                "workspace_id": workspace_id,
            },
        )
        total = body.get("total_cost") if isinstance(body, dict) else None
        if not isinstance(total, int | float):
            raise AppError("Prolific did not return a study cost.", "prolific_rejected")
        return int(round(total))

    def list_workspaces(self) -> list[dict[str, Any]]:
        """Return workspaces on this token.

        Returns:
            Workspace objects.
        """
        return _results(self.request("GET", "/workspaces/"))

    def workspace_balance(self, workspace_id: str) -> dict[str, Any]:
        """Return the workspace balance.

        Args:
            workspace_id: Workspace id.

        Returns:
            Balance object. Amounts are in cents or pence.
        """
        body = self.request("GET", f"/workspaces/{workspace_id}/balance/")
        if not isinstance(body, dict):
            raise AppError("Prolific did not return a workspace balance.", "prolific_rejected")
        return body

    def list_projects(self, workspace_id: str) -> list[dict[str, Any]]:
        """Return projects in a workspace.

        Args:
            workspace_id: Workspace id.

        Returns:
            Project objects.
        """
        return _results(self.request("GET", f"/workspaces/{workspace_id}/projects/"))

    def create_study(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create an unpublished study.

        Args:
            payload: Study body.

        Returns:
            Created study.
        """
        body = self.request("POST", "/studies/", json=payload)
        if not isinstance(body, dict) or not body.get("id"):
            raise AppError("Prolific did not return a study id.", "prolific_rejected")
        return body

    def study_cost(self, study_id: str) -> dict[str, Any]:
        """Return the projected cost breakdown.

        Args:
            study_id: Study id.

        Returns:
            Cost object with rewards, fees, and tax.
        """
        body = self.request("GET", f"/studies/{study_id}/cost/", params={"is_projected": "true"})
        return body if isinstance(body, dict) else {}

    def transition(self, study_id: str, action: str) -> dict[str, Any]:
        """Change a study's status.

        Args:
            study_id: Study id.
            action: PUBLISH, PAUSE, START, or STOP.

        Returns:
            Transition response.
        """
        body = self.request(
            "POST",
            f"/studies/{study_id}/transition/",
            json={"action": action},
        )
        return body if isinstance(body, dict) else {}

    def get_study(self, study_id: str) -> dict[str, Any]:
        """Return one study.

        Args:
            study_id: Study id.

        Returns:
            Study object.
        """
        body = self.request("GET", f"/studies/{study_id}/")
        return body if isinstance(body, dict) else {}

    def submission_counts(self, study_id: str) -> dict[str, int]:
        """Count submissions by status.

        Args:
            study_id: Study id.

        Returns:
            Status to count.
        """
        body = self.request("GET", f"/studies/{study_id}/submissions/counts/")
        if not isinstance(body, dict):
            return {}
        counts: dict[str, int] = {}
        for key, value in body.items():
            if isinstance(value, int | float):
                counts[str(key)] = int(value)
        return counts

    def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        """Send one API call and retry a single rate-limit response.

        Args:
            method: HTTP method.
            path: Path under the API base.
            json: JSON body.
            params: Query parameters.

        Returns:
            Parsed JSON.

        Raises:
            AppError: The token is missing, the host cannot be reached, or Prolific rejects the call.
        """
        if not self.token:
            raise AppError(_NOT_CONFIGURED, "prolific_not_configured")
        url = f"{self.base}/{path.lstrip('/')}"
        headers = {"Authorization": f"Token {self.token}", "Accept": "application/json"}
        try:
            with httpx.Client(transport=self.transport, timeout=60.0, headers=headers) as client:
                response = client.request(method, url, json=json, params=params)
                if response.status_code == 429:
                    time.sleep(1)
                    response = client.request(method, url, json=json, params=params)
        except httpx.HTTPError as exc:
            raise AppError("Prolific could not be reached.", "prolific_unavailable") from exc
        return _parse(response, self.token)


def _results(body: Any) -> list[dict[str, Any]]:
    """Read a results list.

    Args:
        body: Parsed JSON.

    Returns:
        Object rows.
    """
    rows = body.get("results") if isinstance(body, dict) else body
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _parse(response: httpx.Response, token: str) -> Any:
    """Turn a response into JSON or an application error.

    Args:
        response: Prolific response.
        token: Token to remove from any error text.

    Returns:
        Parsed body.

    Raises:
        AppError: Prolific rejected the call.
    """
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code < 400:
        return body
    detail = _detail(body) or f"Prolific returned {response.status_code}."
    detail = detail.replace(token, "[REDACTED]")
    code = "prolific_unauthorized" if response.status_code == 401 else "prolific_rejected"
    status = response.status_code if response.status_code < 500 else 502
    raise AppError(detail, code, status)


def _detail(body: Any) -> str:
    """Pull a short message out of a Prolific error body.

    Args:
        body: Parsed JSON.

    Returns:
        Message text, possibly empty.
    """
    if not isinstance(body, dict):
        return ""
    error = body.get("error") if isinstance(body.get("error"), dict) else body
    if not isinstance(error, dict):
        return str(body.get("error") or "")[:500]
    detail = error.get("detail") or error.get("title") or error.get("error")
    if isinstance(detail, list):
        return "; ".join(str(item) for item in detail)[:500]
    if isinstance(detail, dict):
        # Reason: field errors arrive nested, such as {"2": {"non_field_errors": [...]}}.
        return " ".join(_messages(detail))[:500]
    return str(detail or "")[:500]


def _messages(value: Any) -> list[str]:
    """Collect the error sentences inside a nested Prolific error.

    Args:
        value: Error detail.

    Returns:
        Sentences in the order Prolific listed them.
    """
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        return [text for item in value.values() for text in _messages(item)]
    if isinstance(value, list):
        return [text for item in value for text in _messages(item)]
    return []
