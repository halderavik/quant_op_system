"""Model role configuration and account availability checks."""

from app.config import Settings


class ModelRouter:
    """Report configured model ids and, on demand, which ids the account can see."""

    def __init__(self, settings: Settings) -> None:
        """Store settings.

        Args:
            settings: Application settings.
        """
        self.settings = settings

    def status(self) -> dict:
        """Return configuration without calling the network.

        Returns:
            Availability based on whether a key is present, plus role ids.
        """
        configured = {
            role: self.settings.model_for(role)
            for role in (
                "orchestrator",
                "questionnaire",
                "tabspec",
                "analysis",
                "coding",
                "validator",
                "general",
            )
        }
        if not self.settings.llm_configured:
            return {
                "available": False,
                "reason": "OPENAI_API_KEY is not set. Add it to backend/.env and restart.",
                "configured": configured,
                "fallback": self.settings.model_fallback,
            }
        claude_ids = {
            model_id
            for model_id in (*configured.values(), self.settings.model_fallback)
            if self.settings.provider_for(model_id) == "anthropic"
        }
        if claude_ids and not self.settings.anthropic_api_key.strip():
            return {
                "available": True,
                "reason": (
                    "ANTHROPIC_API_KEY is not set. Add it to backend/.env and restart. "
                    "Coding jobs need it."
                ),
                "configured": configured,
                "fallback": self.settings.model_fallback,
            }
        return {
            "available": True,
            "configured": configured,
            "fallback": self.settings.model_fallback,
        }

    def probe(self) -> dict:
        """Ask the account which configured model ids exist.

        Returns:
            Probe result. The API key is not included.
        """
        current = self.status()
        if not self.settings.llm_configured:
            return current
        from openai import OpenAI

        try:
            client = OpenAI(api_key=self.settings.openai_api_key)
            seen = {item.id for item in client.models.list()}
        except Exception as exc:
            return {
                "available": False,
                "reason": f"Model probe failed ({exc.__class__.__name__}).",
                "configured": current["configured"],
                "fallback": self.settings.model_fallback,
            }
        configured_ids = {*current["configured"].values(), self.settings.model_fallback}
        openai_ids = {
            model_id
            for model_id in configured_ids
            if self.settings.provider_for(model_id) == "openai"
        }
        claude_ids = configured_ids - openai_ids
        missing = sorted(openai_ids - seen)
        # Reason: the OpenAI model list cannot confirm a Claude id. A present key is enough.
        if claude_ids and not self.settings.anthropic_api_key.strip():
            missing.extend(sorted(claude_ids))
        return {
            "available": not missing,
            "missing_models": missing,
            "configured": current["configured"],
            "fallback": self.settings.model_fallback,
        }
