"""Application errors returned as structured API responses."""


class AppError(Exception):
    """A user-facing failure with a stable code and HTTP status.

    Args:
        message: Actionable explanation safe to show in the UI.
        code: Stable machine-readable error code.
        status_code: HTTP status to return.
    """

    def __init__(self, message: str, code: str = "bad_request", status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
