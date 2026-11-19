"""Keep finished model answers so a retried import or plan continues instead of starting over.

A questionnaire import or a programming plan is many model calls. When one fails
(credits, a timeout, a cancel) the person sends the request again; every call
that already finished is read from here. The key is the model, the instructions,
the prompt, and the answer type, so any change to the file, the lessons, or the
prompt makes a new key. Entries older than ``MAX_AGE_DAYS`` are ignored.
"""

import hashlib
import json
import logging
import time
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)
MAX_AGE_DAYS = 14


def cache_key(model: str, instructions: str, prompt: str, output_type: type) -> str:
    """A stable key for one model call."""
    digest = hashlib.sha256()
    for part in (model, output_type.__qualname__, instructions, prompt):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def _path(root: Path, key: str) -> Path:
    return root / "cache" / "model_calls" / key[:2] / f"{key}.json"


def load(root: Path, key: str, output_type: type[BaseModel]) -> BaseModel | None:
    """A saved answer for ``key``, or None when there is none, it is too old, or it no longer fits."""
    path = _path(root, key)
    try:
        if not path.exists() or time.time() - path.stat().st_mtime > MAX_AGE_DAYS * 86400:
            return None
        return output_type.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a broken entry is just a miss
        return None


def save(root: Path, key: str, answer: BaseModel) -> None:
    """Keep an answer for later retries. Failures to write are ignored."""
    path = _path(root, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(answer.model_dump(mode="json")), encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.warning("Could not cache a model answer at %s", path)
