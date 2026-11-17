"""Rules learned from corrections to planned survey logic.

Revision ID: 004_programming_lessons
Revises: 003_connectors
Create Date: 2026-11-17
"""

from alembic import op

from app.db.base import Base
from app.models import tables as _tables  # noqa: F401

revision = "004_programming_lessons"
down_revision = "003_connectors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the lessons table if it is missing."""
    Base.metadata.tables["programming_lessons"].create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    """Drop the lessons table."""
    Base.metadata.tables["programming_lessons"].drop(bind=op.get_bind(), checkfirst=True)
