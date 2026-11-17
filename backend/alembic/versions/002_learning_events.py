"""Learning events captured from edits, follow-ups, downloads, and ratings.

Revision ID: 002_learning_events
Revises: 001_initial
Create Date: 2026-11-12
"""

from alembic import op

from app.db.base import Base
from app.models import tables as _tables  # noqa: F401

revision = "002_learning_events"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the learning_events table if it is missing."""
    Base.metadata.tables["learning_events"].create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    """Drop the learning_events table."""
    Base.metadata.tables["learning_events"].drop(bind=op.get_bind(), checkfirst=True)
