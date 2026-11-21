"""Programmer to-do, XML comparison, and logic test routes for the Decipher survey."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.repositories.records import ProjectRepository

router = APIRouter()


class TodoIds(BaseModel):
    """The to-dos an action applies to."""

    ids: list[str] = Field(min_length=1, max_length=500)


class MarkTodos(TodoIds):
    """Mark to-dos done, or reopen them."""

    done: bool = True


class ReferenceXml(BaseModel):
    """Survey XML to compare with; it is not stored."""

    xml: str = Field(min_length=1)


@router.get("/projects/{project_id}/decipher/todos")
def list_todos_route(project_id: str, db: Session = Depends(get_db)) -> dict:
    """List the programmer to-dos of the latest questionnaire.

    Args:
        project_id: Project id.
        db: Session.

    Returns:
        To-do rows, counts, and whether the saved XML is out of date.
    """
    from app.services.programmer_todos import list_todos

    ProjectRepository(db).get(project_id)
    return list_todos(db, project_id)


@router.post("/projects/{project_id}/decipher/todos/mark")
def mark_todos_route(
    project_id: str, body: MarkTodos, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Mark to-dos done or reopen them, then rebuild the XML without uploading.

    Args:
        project_id: Project id.
        body: To-do ids and the done flag.
        request: Current request.
        db: Session.

    Returns:
        The new to-do list and a summary.
    """
    from app.services.programmer_todos import mark_todos

    ProjectRepository(db).get(project_id)
    return mark_todos(
        db, request.app.state.storage, request.app.state.settings, project_id, body.ids, body.done
    )


@router.post("/projects/{project_id}/decipher/todos/fix")
async def fix_todos_route(
    project_id: str, body: TodoIds, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Fix question to-dos with the AI planner, check them with the reviewer, rebuild the XML.

    Args:
        project_id: Project id.
        body: To-do ids.
        request: Current request.
        db: Session.

    Returns:
        The new to-do list, how many were fixed, and a summary.
    """
    from app.services.programmer_todos import fix_todos

    ProjectRepository(db).get(project_id)
    return await fix_todos(
        db, request.app.state.storage, request.app.state.settings, project_id, body.ids
    )


@router.post("/projects/{project_id}/decipher/compare")
def compare_xml_route(project_id: str, body: ReferenceXml, db: Session = Depends(get_db)) -> dict:
    """Compare the generated XML with an edited or reference XML, question by question.

    Args:
        project_id: Project id.
        body: Reference XML.
        db: Session.

    Returns:
        Match scores and one row per question with both XML snippets and the checks.
    """
    from app.services.xml_compare import compare_with_reference

    ProjectRepository(db).get(project_id)
    return compare_with_reference(db, project_id, body.xml)


class LogicQaIn(BaseModel):
    """How many respondents to simulate."""

    respondents: int = Field(default=400, ge=50, le=2000)


@router.post("/projects/{project_id}/decipher/qa")
def logic_qa_route(project_id: str, body: LogicQaIn, db: Session = Depends(get_db)) -> dict:
    """Simulate respondents through the survey XML and check every base and terminate.

    Args:
        project_id: Project id.
        body: Respondent count.
        db: Session.

    Returns:
        Agreement, issues with example answers, per-question counts, and warnings.
    """
    from app.services.logic_qa_run import logic_qa

    ProjectRepository(db).get(project_id)
    return logic_qa(db, project_id, body.respondents)
