"""Programmer to-dos: what programming could not carry out, listed, marked done, or fixed.

A to-do is one ``unresolved`` line on a question's programming or on a derived
variable of the latest questionnaire. They also appear as ``PROGRAMMER TODO``
comments in the XML; this module lets a person work through them:

* **Mark done** moves a to-do to ``done_todos`` (handled in Decipher, or not
  needed), so it leaves the XML comments; **reopen** moves it back.
* **Fix with AI** plans the chosen questions again with their to-dos as problems,
  asks the reviewer to check the result, and keeps whatever is still open as a to-do.
  The chosen to-dos are kept in ``requested``: the person asked for them, so the
  reviewer treats them as instructions from then on.

Each change saves a new questionnaire version and rebuilds the XML. Nothing is
uploaded to Decipher; the upload still waits for its own click.
"""

import asyncio
import hashlib
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import AppError
from app.repositories.records import ArtifactRepository
from app.schemas.questionnaire import ProgrammingSpec, Question, Questionnaire
from app.services.storage import Storage

MAX_FIX_QUESTIONS = 40


def todo_id(owner: str, text: str) -> str:
    """A stable id for one to-do: the same owner and wording give the same id."""
    return hashlib.sha1(f"{owner}\0{text}".encode()).hexdigest()[:12]


def todo_rows(document: Questionnaire) -> list[dict[str, Any]]:
    """Every open and done to-do in questionnaire order.

    Args:
        document: Questionnaire with programming.

    Returns:
        Rows with id, owner, owner kind, question text, to-do text, source, and done flag.
    """
    rows: list[dict[str, Any]] = []
    for question in document.questions:
        spec = question.programming
        if spec is None:
            continue
        for text, done in [
            *((t, False) for t in spec.unresolved),
            *((t, True) for t in spec.done_todos),
        ]:
            rows.append(_row(question.id, "question", question.text, text, done))
    for variable in document.derived_variables:
        title = variable.label or variable.definition
        for text, done in [
            *((t, False) for t in variable.unresolved),
            *((t, True) for t in variable.done_todos),
        ]:
            rows.append(_row(variable.id, "derived", title, text, done))
    return rows


def _row(owner: str, kind: str, title: str, text: str, done: bool) -> dict[str, Any]:
    review = text.startswith("Review: ")
    return {
        "id": todo_id(owner, text),
        "owner": owner,
        "owner_kind": kind,
        "title": title[:200],
        "text": text.removeprefix("Review: "),
        "source": "review" if review else "planner",
        "done": done,
        "fixable": kind == "question" and not done,
    }


def list_todos(db: Session, project_id: str) -> dict[str, Any]:
    """The to-dos of the latest questionnaire and whether the saved XML is up to date.

    Args:
        db: Session.
        project_id: Project id.

    Returns:
        To-do rows, counts, and the questionnaire and XML versions.
    """
    current = ArtifactRepository(db).latest_of_type(project_id, "questionnaire")
    if current is None:
        return {
            "todos": [],
            "open": 0,
            "done": 0,
            "questionnaire_version": None,
            "xml_stale": False,
        }
    rows = todo_rows(Questionnaire.model_validate(current.content))
    survey = ArtifactRepository(db).latest_of_type(project_id, "decipher_survey")
    built_from = (survey.content or {}).get("questionnaire_version") if survey else None
    return {
        "todos": rows,
        "open": sum(not row["done"] for row in rows),
        "done": sum(row["done"] for row in rows),
        "questionnaire_version": current.version,
        "xml_stale": survey is not None and built_from != current.version,
    }


def mark_todos(
    db: Session,
    storage: Storage,
    settings: Settings,
    project_id: str,
    ids: list[str],
    done: bool,
) -> dict[str, Any]:
    """Mark to-dos done, or reopen them, then rebuild the XML.

    Args:
        db: Session.
        storage: Storage service.
        settings: Server settings.
        project_id: Project id.
        ids: To-do ids.
        done: True to mark done, False to reopen.

    Returns:
        The new to-do list and a summary.
    """
    document = _latest(db, project_id)
    wanted = set(ids)
    moved = 0
    questions: list[Question] = []
    for question in document.questions:
        spec = question.programming
        if spec is None:
            questions.append(question)
            continue
        unresolved, finished, count = _move(
            question.id, spec.unresolved, spec.done_todos, wanted, done
        )
        moved += count
        questions.append(
            question.model_copy(
                update={
                    "programming": spec.model_copy(
                        update={"unresolved": unresolved, "done_todos": finished}
                    )
                }
            )
            if count
            else question
        )
    derived = []
    for variable in document.derived_variables:
        unresolved, finished, count = _move(
            variable.id, variable.unresolved, variable.done_todos, wanted, done
        )
        moved += count
        derived.append(
            variable.model_copy(update={"unresolved": unresolved, "done_todos": finished})
            if count
            else variable
        )
    if not moved:
        raise AppError(
            "Those to-dos were not found. Refresh the list and try again.", "not_found", 404
        )
    document = document.model_copy(update={"questions": questions, "derived_variables": derived})
    verb = "Marked" if done else "Reopened"
    summary = f"{verb} {moved} to-do{'s' if moved != 1 else ''}."
    return _save_and_rebuild(db, storage, settings, project_id, document, summary)


def _move(
    owner: str, unresolved: list[str], finished: list[str], wanted: set[str], done: bool
) -> tuple[list[str], list[str], int]:
    """Move the wanted to-dos of one owner between the open and done lists."""
    source, target = (unresolved, finished) if done else (finished, unresolved)
    picked = [text for text in source if todo_id(owner, text) in wanted]
    if not picked:
        return unresolved, finished, 0
    kept = [text for text in source if text not in picked]
    moved_to = list(dict.fromkeys([*target, *picked]))
    return (kept, moved_to, len(picked)) if done else (moved_to, kept, len(picked))


async def fix_todos(
    db: Session,
    storage: Storage,
    settings: Settings,
    project_id: str,
    ids: list[str],
) -> dict[str, Any]:
    """Plan the questions of the chosen to-dos again, check the result, and rebuild the XML.

    The planner gets each chosen to-do as a problem to fix. The reviewer then reads
    the rebuilt XML of those questions; what it still finds stays a to-do. To-dos
    that were not chosen are never dropped by a fix.

    Args:
        db: Session.
        storage: Storage service.
        settings: Server settings.
        project_id: Project id.
        ids: To-do ids. Only question to-dos can be fixed this way.

    Returns:
        The new to-do list, counts of fixed and remaining to-dos, and a summary.
    """
    from app.engines.decipher import compile_decipher
    from app.learning.lessons import active_lessons
    from app.services.program_review import review
    from app.services.programming_spec import (
        BATCH,
        PARALLEL,
        inherit_piped_lists,
        merge_derived,
        settle,
    )
    from app.services.programming_spec import _apply as apply_plans
    from app.services.programming_spec import _plan_batch as plan_batch

    if not settings.llm_configured:
        raise AppError(
            "No AI model is set up, so to-dos can only be marked done.", "llm_not_configured", 400
        )
    document = _latest(db, project_id)
    wanted = set(ids)
    problems: dict[str, list[str]] = {}
    for question in document.questions:
        for text in question.programming.unresolved if question.programming else []:
            if todo_id(question.id, text) in wanted:
                problems.setdefault(question.id, []).append(text.removeprefix("Review: "))
    if not problems:
        raise AppError("Pick at least one open question to-do to fix.", "bad_request", 400)
    if len(problems) > MAX_FIX_QUESTIONS:
        raise AppError(
            f"Fix up to {MAX_FIX_QUESTIONS} questions at a time; {len(problems)} were picked.",
            "bad_request",
            400,
        )
    document = _with_requests(document, problems)
    lessons = active_lessons(db)
    # Reason: SQLite keeps its lock until commit, and the model calls take minutes.
    db.commit()
    session_id = f"todo-fix-{uuid.uuid4().hex[:8]}"
    limit = asyncio.Semaphore(PARALLEL)
    targets = [question for question in document.questions if question.id in problems]
    groups = [targets[i : i + BATCH] for i in range(0, len(targets), BATCH)]
    results = await asyncio.gather(
        *(
            plan_batch(settings, document, group, problems, session_id, limit, lessons)
            for group in groups
        )
    )
    before = {question.id: question for question in document.questions}
    plans = [
        plan for result in results for plan in result.questions if plan.question_id in problems
    ]
    document = merge_derived(document, [plan for result in results for plan in result.derived])
    document = settle(inherit_piped_lists(apply_plans(document, plans)))
    program = compile_decipher(document)
    findings = await review(
        settings, document, program.xml, session_id, limit, lessons, only=set(problems)
    )
    document = _keep_open(document, before, problems, findings)
    remaining = sum(
        len(question.programming.unresolved)
        for question in document.questions
        if question.id in problems and question.programming
    )
    chosen = sum(len(items) for items in problems.values())
    still = sum(
        1
        for question in document.questions
        if question.id in problems and question.programming
        for text in question.programming.unresolved
        if text.removeprefix("Review: ") in problems[question.id]
    )
    fixed = max(chosen - still, 0)
    summary = (
        f"Fixed {fixed} of {chosen} to-do{'s' if chosen != 1 else ''} in "
        f"{len(problems)} question{'s' if len(problems) != 1 else ''}; the reviewer checked the result."
    )
    if remaining:
        summary += (
            f" {remaining} to-do{'s' if remaining != 1 else ''} still open on those questions."
        )
    outcome = _save_and_rebuild(db, storage, settings, project_id, document, summary)
    outcome.update({"fixed": fixed, "remaining": remaining})
    return outcome


def _keep_open(
    document: Questionnaire,
    before: dict[str, Question],
    problems: dict[str, list[str]],
    findings: dict[str, list[str]],
) -> Questionnaire:
    """Keep to-dos that were not picked, and add what the reviewer still finds."""
    questions = []
    for question in document.questions:
        if question.id not in problems:
            questions.append(question)
            continue
        old = before[question.id].programming or ProgrammingSpec()
        spec = (question.programming or ProgrammingSpec()).model_copy(deep=True)
        picked = set(problems[question.id])
        untouched = [text for text in old.unresolved if text.removeprefix("Review: ") not in picked]
        reviewed = [f"Review: {item}" for item in findings.get(question.id, [])]
        spec.unresolved = list(dict.fromkeys([*spec.unresolved, *untouched, *reviewed]))
        spec.done_todos = list(old.done_todos)
        spec.requested = list(old.requested)
        questions.append(question.model_copy(update={"programming": spec}))
    return document.model_copy(update={"questions": questions})


def _with_requests(document: Questionnaire, problems: dict[str, list[str]]) -> Questionnaire:
    """Record the chosen to-dos as changes the person asked for.

    The reviewer judges the XML against the written instructions; without this it
    would report a requested change, such as a terminate the notes never mention,
    as going beyond the questionnaire.
    """
    questions = []
    for question in document.questions:
        if question.id not in problems:
            questions.append(question)
            continue
        spec = (question.programming or ProgrammingSpec()).model_copy(deep=True)
        spec.requested = list(dict.fromkeys([*spec.requested, *problems[question.id]]))
        questions.append(question.model_copy(update={"programming": spec}))
    return document.model_copy(update={"questions": questions})


def _latest(db: Session, project_id: str) -> Questionnaire:
    current = ArtifactRepository(db).latest_of_type(project_id, "questionnaire")
    if current is None:
        raise AppError("There is no questionnaire in this project yet.", "not_found", 404)
    return Questionnaire.model_validate(current.content)


def _save_and_rebuild(
    db: Session,
    storage: Storage,
    settings: Settings,
    project_id: str,
    document: Questionnaire,
    summary: str,
) -> dict[str, Any]:
    """Save the questionnaire, rebuild the XML (never uploading), and list the to-dos."""
    from app.services.decipher_program import program_decipher_survey
    from app.services.documents import save_questionnaire

    save_questionnaire(db, project_id, document, created_by="programmer_todos", summary=summary)
    artifact_id = None
    survey = ArtifactRepository(db).latest_of_type(project_id, "decipher_survey")
    # Reason: XML someone else programmed and uploaded here is never replaced by ours.
    if survey is not None and (survey.content or {}).get("source") != "uploaded_xml":
        try:
            artifact_id = program_decipher_survey(
                db, storage, project_id, settings, confirmed=False
            )["artifact_id"]
        except AppError as exc:
            summary += f" The XML was not rebuilt: {exc.message}"
    return {**list_todos(db, project_id), "summary": summary, "artifact_id": artifact_id}


__all__ = ["fix_todos", "list_todos", "mark_todos", "todo_id", "todo_rows"]
