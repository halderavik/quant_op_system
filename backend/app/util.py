"""Small helpers shared by services and engines."""

import hashlib
import json
import uuid
from typing import Any


def new_id() -> str:
    """Return a new UUID string.

    Returns:
        Canonical UUID text.
    """
    return str(uuid.uuid4())


def canonical_hash(payload: Any) -> str:
    """Hash canonical JSON so artifact revisions have a stable fingerprint.

    Args:
        payload: JSON-serialisable object.

    Returns:
        Hex SHA-256 digest.
    """
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Hash raw file bytes.

    Args:
        data: File contents.

    Returns:
        Hex SHA-256 digest.
    """
    return hashlib.sha256(data).hexdigest()
