"""Project, artifact, dataset, and task persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Artifact, ArtifactRevision, Conversation, Dataset, Message, Project
from app.repositories.records_files import FileRepository, JobRepository
from app.repositories.records_tasks import TaskRepository
from app.util import canonical_hash, new_id

__all__ = [
    "ArtifactRepository",
    "DatasetRepository",
    "FileRepository",
    "JobRepository",
    "ProjectRepository",
    "TaskRepository",
]


def _now() -> datetime:
    """Return the current UTC time.

    Returns:
        Timezone-aware timestamp.
    """
    return datetime.now(timezone.utc)


class ProjectRepository:
    """Create and load projects and conversations."""

    def __init__(self, db: Session) -> None:
        """Bind a session.

        Args:
            db: SQLAlchemy session.
        """
        self.db = db

    def create(self, name: str, study_context: dict[str, Any] | None = None) -> Project:
        """Insert a project and its first conversation.

        Args:
            name: Project name.
            study_context: Optional study defaults.

        Returns:
            Project.
        """
        project = Project(
            id=new_id(),
            name=name,
            study_context=study_context or {},
            created_at=_now(),
            updated_at=_now(),
        )
        self.db.add(project)
        self.db.flush()
        self.db.add(
            Conversation(
                id=new_id(),
                project_id=project.id,
                title="Research chat",
                sdk_session_id=new_id(),
                created_at=_now(),
                updated_at=_now(),
            )
        )
        self.db.flush()
        return project

    def list(self) -> list[Project]:
        """Return projects newest first.

        Returns:
            Projects.
        """
        return list(self.db.scalars(select(Project).order_by(Project.created_at.desc())))

    def get(self, project_id: str) -> Project:
        """Return one project or raise a not-found error.

        Args:
            project_id: Project id.

        Returns:
            Project.
        """
        project = self.db.get(Project, project_id)
        if project is None:
            raise AppError("Project not found", "not_found", 404)
        return project

    def conversation(self, conversation_id: str) -> Conversation:
        """Return one conversation.

        Args:
            conversation_id: Conversation id.

        Returns:
            Conversation.
        """
        row = self.db.get(Conversation, conversation_id)
        if row is None:
            raise AppError("Conversation not found", "not_found", 404)
        return row

    def conversations(self, project_id: str) -> list[Conversation]:
        """List conversations in a project.

        Args:
            project_id: Project id.

        Returns:
            Conversations.
        """
        return list(
            self.db.scalars(select(Conversation).where(Conversation.project_id == project_id))
        )

    def add_message(
        self, conversation_id: str, role: str, content: str, task_id: str | None = None
    ) -> Message:
        """Append a message.

        Args:
            conversation_id: Conversation id.
            role: ``user`` or ``assistant``.
            content: Message text.
            task_id: Optional task id.

        Returns:
            Message.
        """
        current = self.db.scalars(
            select(Message).where(Message.conversation_id == conversation_id)
        ).all()
        message = Message(
            id=new_id(),
            conversation_id=conversation_id,
            role=role,
            content=content,
            task_id=task_id,
            sequence=len(current) + 1,
            created_at=_now(),
        )
        self.db.add(message)
        self.db.flush()
        return message

    def messages(self, conversation_id: str) -> list[Message]:
        """Return messages in order.

        Args:
            conversation_id: Conversation id.

        Returns:
            Messages.
        """
        return list(
            self.db.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.sequence)
            )
        )


class ArtifactRepository:
    """Immutable artifact revisions with optimistic version checks."""

    def __init__(self, db: Session) -> None:
        """Bind a session.

        Args:
            db: SQLAlchemy session.
        """
        self.db = db

    def create(
        self,
        *,
        project_id: str,
        artifact_type: str,
        name: str,
        content: dict[str, Any],
        content_schema: str,
        created_by: str = "user",
        derived_from: list[dict[str, Any]] | None = None,
        validation_status: str = "pending",
        artifact_id: str | None = None,
        expected_version: int | None = None,
    ) -> ArtifactRevision:
        """Write a new revision, creating the artifact identity when needed.

        Args:
            project_id: Project id.
            artifact_type: Artifact type.
            name: Display name.
            content: Canonical JSON.
            content_schema: Schema name.
            created_by: ``user`` or an agent id.
            derived_from: Upstream artifact references.
            validation_status: Validator status.
            artifact_id: Existing artifact to revise.
            expected_version: Required current version when set.

        Returns:
            New revision.
        """
        if artifact_id:
            artifact = self.db.get(Artifact, artifact_id)
            if artifact is None:
                raise AppError("Artifact not found", "not_found", 404)
            latest = self.latest(artifact_id)
            current = latest.version if latest else 0
            if expected_version is not None and expected_version != current:
                raise AppError(
                    "This artifact was updated. Reload it and apply your edit again.",
                    "version_conflict",
                    409,
                )
            version = current + 1
            parent = current or None
            artifact.name = name
            artifact.updated_at = _now()
        else:
            artifact = Artifact(
                id=new_id(),
                project_id=project_id,
                type=artifact_type,
                name=name,
                created_at=_now(),
                updated_at=_now(),
            )
            self.db.add(artifact)
            self.db.flush()
            version = 1
            parent = None
        revision = ArtifactRevision(
            id=new_id(),
            artifact_id=artifact.id,
            version=version,
            parent_version=parent,
            content_schema=content_schema,
            content=content,
            derived_from=derived_from or [],
            stale=False,
            validation_status=validation_status,
            content_hash=canonical_hash(content),
            created_by=created_by,
            created_at=_now(),
        )
        self.db.add(revision)
        self.db.flush()
        if artifact_type == "questionnaire":
            self.mark_stale(project_id, artifact.id, version)
        return revision

    def latest(self, artifact_id: str) -> ArtifactRevision | None:
        """Return the highest revision.

        Args:
            artifact_id: Artifact id.

        Returns:
            Revision or None.
        """
        rows = list(
            self.db.scalars(
                select(ArtifactRevision)
                .where(ArtifactRevision.artifact_id == artifact_id)
                .order_by(ArtifactRevision.version.desc())
            )
        )
        return rows[0] if rows else None

    def revision(self, artifact_id: str, version: int) -> ArtifactRevision:
        """Return one revision.

        Args:
            artifact_id: Artifact id.
            version: Version number.

        Returns:
            Revision.
        """
        row = self.db.scalar(
            select(ArtifactRevision).where(
                ArtifactRevision.artifact_id == artifact_id,
                ArtifactRevision.version == version,
            )
        )
        if row is None:
            raise AppError("Revision not found", "not_found", 404)
        return row

    def history(self, artifact_id: str) -> list[ArtifactRevision]:
        """Return revisions oldest first.

        Args:
            artifact_id: Artifact id.

        Returns:
            Revisions.
        """
        return list(
            self.db.scalars(
                select(ArtifactRevision)
                .where(ArtifactRevision.artifact_id == artifact_id)
                .order_by(ArtifactRevision.version)
            )
        )

    def list_project(self, project_id: str) -> list[Artifact]:
        """List artifact identities in a project.

        Args:
            project_id: Project id.

        Returns:
            Artifacts.
        """
        return list(self.db.scalars(select(Artifact).where(Artifact.project_id == project_id)))

    def latest_of_type(self, project_id: str, artifact_type: str) -> ArtifactRevision | None:
        """Return the newest revision of a type in a project.

        Args:
            project_id: Project id.
            artifact_type: Artifact type.

        Returns:
            Revision or None.
        """
        artifacts = [item for item in self.list_project(project_id) if item.type == artifact_type]
        revisions = [self.latest(item.id) for item in artifacts]
        revisions = [item for item in revisions if item is not None]
        if not revisions:
            return None
        return sorted(revisions, key=lambda item: item.created_at)[-1]

    def mark_stale(self, project_id: str, upstream_id: str, new_version: int) -> None:
        """Flag revisions derived from an older upstream version.

        Args:
            project_id: Project id.
            upstream_id: Artifact that just changed.
            new_version: New upstream version.
        """
        for artifact in self.list_project(project_id):
            for revision in self.history(artifact.id):
                for source in revision.derived_from or []:
                    if (
                        source.get("id") == upstream_id
                        and int(source.get("version") or 0) < new_version
                    ):
                        revision.stale = True


class DatasetRepository:
    """Dataset metadata records."""

    def __init__(self, db: Session) -> None:
        """Bind a session.

        Args:
            db: SQLAlchemy session.
        """
        self.db = db

    def add(self, **kwargs: Any) -> Dataset:
        """Insert a dataset row.

        Args:
            **kwargs: Column values.

        Returns:
            Dataset.
        """
        row = Dataset(id=kwargs.pop("id", new_id()), created_at=_now(), **kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def get(self, dataset_id: str) -> Dataset:
        """Return a dataset.

        Args:
            dataset_id: Dataset id.

        Returns:
            Dataset.
        """
        row = self.db.get(Dataset, dataset_id)
        if row is None:
            raise AppError("Dataset not found", "not_found", 404)
        return row

    def list(self, project_id: str) -> list[Dataset]:
        """List datasets in a project.

        Args:
            project_id: Project id.

        Returns:
            Datasets.
        """
        return list(self.db.scalars(select(Dataset).where(Dataset.project_id == project_id)))
