"""Encrypt connector tokens at rest. Values never reach the browser or the logs."""

import json
import logging
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings

logger = logging.getLogger(__name__)


def _key(settings: Settings) -> bytes:
    """Return the Fernet key, creating a local key file on first use.

    Args:
        settings: Application settings.

    Returns:
        Key bytes.
    """
    configured = settings.connector_secret_key.strip()
    if configured:
        return configured.encode()
    path = Path(settings.storage_root) / "connectors.key"
    if path.exists():
        return path.read_bytes().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    path.write_bytes(key)
    return key


def seal(settings: Settings, values: dict[str, Any]) -> str:
    """Encrypt a dictionary of secrets.

    Args:
        settings: Application settings.
        values: Tokens and other secrets.

    Returns:
        Ciphertext. Empty when there is nothing to store.
    """
    if not values:
        return ""
    return Fernet(_key(settings)).encrypt(json.dumps(values).encode()).decode()


def unseal(settings: Settings, blob: str) -> dict[str, Any]:
    """Decrypt stored secrets.

    Args:
        settings: Application settings.
        blob: Ciphertext from :func:`seal`.

    Returns:
        Secrets. Empty when the blob is empty or the key changed.
    """
    if not blob:
        return {}
    try:
        return json.loads(Fernet(_key(settings)).decrypt(blob.encode()))
    except (InvalidToken, ValueError):
        logger.warning("Stored connector credentials could not be decrypted; reconnect the connector.")
        return {}
