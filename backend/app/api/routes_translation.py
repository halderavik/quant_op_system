"""Questionnaire translation routes: languages, segments, sign-off, and exports."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.repositories.records import ProjectRepository

router = APIRouter()


class NewLanguageIn(BaseModel):
    """A language to add."""

    language: str = Field(min_length=2, max_length=80)
    notes: str = Field(default="", max_length=2000)


class TranslateIn(BaseModel):
    """Guidance for translating what a language is missing."""

    notes: str = Field(default="", max_length=2000)


class SegmentIn(BaseModel):
    """A reviewer's wording for one segment."""

    key: str = Field(min_length=1, max_length=200)
    text: str = Field(max_length=20000)


class ApproveIn(BaseModel):
    """Who signs the language off."""

    reviewer: str = Field(min_length=1, max_length=120)


@router.get("/projects/{project_id}/translations")
def list_translations(project_id: str, db: Session = Depends(get_db)) -> dict:
    """Every language of the questionnaire and how complete it is."""
    from app.services.translation import overview

    ProjectRepository(db).get(project_id)
    return overview(db, project_id)


@router.get("/projects/{project_id}/translations/{artifact_id}")
def get_translation(project_id: str, artifact_id: str, db: Session = Depends(get_db)) -> dict:
    """One language, segment by segment."""
    from app.services.translation import language_detail

    return language_detail(db, project_id, artifact_id)


@router.post("/projects/{project_id}/translations", status_code=201)
async def add_language(
    project_id: str, body: NewLanguageIn, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Add a language and translate the questionnaire into it with the AI model."""
    from app.services.translation import translate

    ProjectRepository(db).get(project_id)
    return await translate(
        db, request.app.state.settings, project_id, body.language, notes=body.notes
    )


@router.post("/projects/{project_id}/translations/{artifact_id}/translate")
async def translate_missing(
    project_id: str,
    artifact_id: str,
    body: TranslateIn,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Translate what a language is missing, including segments whose source changed."""
    from app.services.translation import translate

    return await translate(
        db, request.app.state.settings, project_id, "", artifact_id=artifact_id, notes=body.notes
    )


@router.put("/projects/{project_id}/translations/{artifact_id}/segments")
def edit_translation_segment(
    project_id: str, artifact_id: str, body: SegmentIn, db: Session = Depends(get_db)
) -> dict:
    """Save a reviewer's wording for one segment; the language goes back to draft."""
    from app.services.translation import edit_segment

    return edit_segment(db, project_id, artifact_id, body.key, body.text)


@router.post("/projects/{project_id}/translations/{artifact_id}/approve")
def approve_translation(
    project_id: str, artifact_id: str, body: ApproveIn, db: Session = Depends(get_db)
) -> dict:
    """Sign off a language once every segment is translated."""
    from app.services.translation import approve

    return approve(db, project_id, artifact_id, body.reviewer)


@router.post("/projects/{project_id}/translations/{artifact_id}/export/{kind}")
def export_translation(
    project_id: str, artifact_id: str, kind: str, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Export one language as docx, pdf, or survey XML (never uploaded)."""
    from app.services.translation import export_language

    return export_language(db, request.app.state.storage, project_id, artifact_id, kind)
