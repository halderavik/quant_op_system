"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.config import Settings, get_settings
from app.db.base import Base
from app.db.session import make_engine, make_session_factory
from app.errors import AppError
from app.models import tables as _tables  # noqa: F401
from app.services.storage import Storage

logger = logging.getLogger("survey_studio")


class _RedactKey(logging.Filter):
    """Remove the API key if it ever reaches a log record."""

    def __init__(self, secret: str) -> None:
        """Store the secret to redact.

        Args:
            secret: API key. Empty when unset.
        """
        super().__init__()
        self.secret = secret

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact the key from the message.

        Args:
            record: Log record.

        Returns:
            True so the record is kept.
        """
        if self.secret and self.secret in str(record.msg):
            record.msg = str(record.msg).replace(self.secret, "[REDACTED]")
        return True


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API, database, and storage for one process.

    Args:
        settings: Optional settings override used by tests.

    Returns:
        FastAPI application.
    """
    active = settings or get_settings()
    logging.getLogger().addFilter(_RedactKey(active.openai_api_key))
    engine = make_engine(active)
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    storage = Storage(active)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """Log a startup error when the API key is missing.

        Args:
            _: FastAPI app.

        Yields:
            None.
        """
        if not active.llm_configured:
            logger.error(
                "OPENAI_API_KEY is not set. Add it to backend/.env and restart. "
                "Questionnaire drafting and open-end coding stay unavailable."
            )
        if active.openai_tracing_disabled:
            try:
                from agents import set_tracing_disabled

                set_tracing_disabled(True)
            except Exception:
                logger.info("OpenAI tracing helper was not imported.")
        yield

    app = FastAPI(title="Survey Research Agent Studio", version="0.1.0", lifespan=lifespan)
    app.state.settings = active
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.storage = storage
    app.add_middleware(
        CORSMiddleware,
        allow_origins=active.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api")

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        """Return a stable error body.

        Args:
            _: Request.
            exc: Application error.

        Returns:
            JSON response.
        """
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        """Return a readable validation error.

        Args:
            _: Request.
            exc: FastAPI validation error.

        Returns:
            JSON response.
        """
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "The request body is not valid.",
                    "details": exc.errors(),
                }
            },
        )

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        """Hide internal exceptions from the client.

        Args:
            _: Request.
            exc: Unexpected exception.

        Returns:
            JSON response.
        """
        logger.exception("Unhandled %s", exc.__class__.__name__)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal",
                    "message": "The request failed. See the server log for the error class.",
                }
            },
        )

    return app


app = create_app()
