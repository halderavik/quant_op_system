"""Connector accounts and connector actions waiting for approval.

Revision ID: 003_connectors
Revises: 002_learning_events
Create Date: 2026-11-16
"""

from alembic import op

from app.db.base import Base
from app.models import tables as _tables  # noqa: F401

revision = "003_connectors"
down_revision = "002_learning_events"
branch_labels = None
depends_on = None

_TABLES = ("connector_accounts", "connector_actions")


def upgrade() -> None:
    """Create the connector tables if they are missing."""
    for name in _TABLES:
        Base.metadata.tables[name].create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    """Drop the connector tables."""
    for name in reversed(_TABLES):
        Base.metadata.tables[name].drop(bind=op.get_bind(), checkfirst=True)
