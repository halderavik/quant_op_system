"""Initial schema.

Revision ID: 001_initial
Revises:
Create Date: 2026-11-07
"""

from alembic import op

from app.db.base import Base
from app.models import tables as _tables  # noqa: F401

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create every table from the SQLAlchemy metadata."""
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """Drop every table."""
    Base.metadata.drop_all(bind=op.get_bind())
