"""SQLite engine factory with WAL and foreign keys."""

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings


def resolve_database_url(settings: Settings) -> str:
    """Turn a relative SQLite URL into an absolute one.

    Args:
        settings: Application settings.

    Returns:
        SQLAlchemy database URL safe to open from any working directory.
    """
    url = settings.database_url
    prefix = "sqlite:///"
    if not url.startswith(prefix) or url.startswith("sqlite:///:memory:"):
        return url
    raw = url[len(prefix) :]
    path = Path(raw)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"{prefix}{path.as_posix()}"


def make_engine(settings: Settings) -> Engine:
    """Create a SQLite engine for the configured database URL.

    Args:
        settings: Application settings.

    Returns:
        Engine with WAL and foreign keys enabled on each connection.
    """
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        resolve_database_url(settings),
        connect_args={"check_same_thread": False},
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _enable_sqlite(dbapi_connection: object, _: object) -> None:
        """Turn on WAL and foreign keys for a new SQLite connection.

        Args:
            dbapi_connection: DB-API connection object.
            _: Unused connection record.
        """
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        # Reason: overlapping chat writes should wait out a short transaction.
        cursor.execute("PRAGMA busy_timeout=8000")
        cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker:
    """Build a session factory bound to ``engine``.

    Args:
        engine: SQLAlchemy engine.

    Returns:
        Session factory that does not expire objects on commit.
    """
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
