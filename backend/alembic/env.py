"""Alembic environment. The URL comes from application settings."""

from sqlalchemy import create_engine

from alembic import context
from app.config import get_settings
from app.db.base import Base
from app.db.session import resolve_database_url
from app.models import tables as _tables  # noqa: F401

target_metadata = Base.metadata


def run_migrations_online() -> None:
    """Run migrations against the configured SQLite database."""
    settings = get_settings()
    engine = create_engine(
        resolve_database_url(settings), connect_args={"check_same_thread": False}
    )
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
