"""Request dependencies."""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session


def get_db(request: Request) -> Iterator[Session]:
    """Yield a session and commit when the request succeeds.

    Args:
        request: Current request.

    Yields:
        SQLAlchemy session.
    """
    db = request.app.state.session_factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
