"""Project-root file storage. Every path is checked against the project directory."""

import re
from pathlib import Path

from app.config import Settings
from app.errors import AppError

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class Storage:
    """Read and write files under ``storage_root/projects/{project_id}``."""

    def __init__(self, settings: Settings) -> None:
        """Store settings and ensure the root exists.

        Args:
            settings: Application settings.
        """
        self.root = settings.storage_root
        self.root.mkdir(parents=True, exist_ok=True)

    def project_root(self, project_id: str) -> Path:
        """Return the absolute directory for one project.

        Args:
            project_id: Project identifier.

        Returns:
            Absolute project directory.
        """
        self._safe_id(project_id)
        path = (self.root / "projects" / project_id).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def resolve(self, project_id: str, relative: str) -> Path:
        """Resolve a relative path and reject anything outside the project.

        Args:
            project_id: Project identifier.
            relative: Path relative to the project root.

        Returns:
            Absolute path inside the project.

        Raises:
            AppError: When the path escapes the project root.
        """
        if relative.startswith(("/", "\\")) or ":" in relative:
            raise AppError("Absolute paths are not allowed", "path_traversal", 400)
        root = self.project_root(project_id)
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root):
            raise AppError("That path is outside the project", "path_traversal", 400)
        return candidate

    def write_bytes(self, project_id: str, relative: str, data: bytes) -> Path:
        """Write bytes to a project-relative path.

        Args:
            project_id: Project identifier.
            relative: Destination relative path.
            data: File contents.

        Returns:
            Absolute path written.
        """
        path = self.resolve(project_id, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def read_bytes(self, project_id: str, relative: str) -> bytes:
        """Read a project-relative file.

        Args:
            project_id: Project identifier.
            relative: Source relative path.

        Returns:
            File bytes.
        """
        return self.resolve(project_id, relative).read_bytes()

    def delete_project(self, project_id: str) -> None:
        """Delete the project directory tree.

        Args:
            project_id: Project identifier.
        """
        import shutil

        root = self.project_root(project_id)
        shutil.rmtree(root, ignore_errors=True)

    @staticmethod
    def safe_filename(name: str) -> str:
        """Reduce a filename to a safe basename.

        Args:
            name: Original filename.

        Returns:
            Basename with unsafe characters replaced.
        """
        base = Path(name).name
        cleaned = _SAFE_NAME.sub("_", base).strip("._")
        return cleaned or "upload.bin"

    @staticmethod
    def _safe_id(project_id: str) -> None:
        """Reject project ids that could be path segments.

        Args:
            project_id: Project identifier.
        """
        if not re.match(r"^[A-Za-z0-9_-]+$", project_id):
            raise AppError("Invalid project id", "bad_project", 400)
