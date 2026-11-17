"""Fully automatic open-end coding with the Ad Hoc AutoCoder.

The AutoCoder (``adhoc_autocoder``, installed from Dhyey-b3/adhoc_autocoder_project
at a pinned commit) discovers a fresh hierarchical codeframe from the question
wording and the answers, then codes every row. No codeframe approval comes
first. This service feeds it one text column, then saves its codeframe and
row codes as the studio's own codeframe and coding artifacts, so frequencies,
the review queue, and the Excel and SPSS exports work the same way as for
coding against an approved codeframe.
"""

import asyncio
import hashlib
import importlib.util
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import AppError
from app.models.tables import Artifact
from app.repositories.records import ArtifactRepository
from app.schemas.coding import Codeframe, CodeNode, CodingAssignment, CodingReport, NetNode
from app.services.coding_run import _blank, _checks, _export, coding_chart_files
from app.services.documents import aggregate_saved_coding
from app.services.execute import _active_dataset, load_frame
from app.services.storage import Storage
from app.services.stored_files import _write_export
from app.util import new_id

ENGINE = "Ad Hoc AutoCoder v0.3"
_ID_NAMES = ("respondent_id", "respid", "resp_id", "uuid", "record", "id")
_LABEL_PREFIX = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_.]*\s*[:.)-]\s+")
_NOT_ANSWER = re.compile(r"not a survey answer|metadata|generator", re.I)


def autocoder_available() -> bool:
    """Return whether the ``adhoc_autocoder`` package is installed."""
    return importlib.util.find_spec("adhoc_autocoder") is not None


def has_codeframe_for(db: Session, project_id: str, variable: str) -> bool:
    """Return whether a saved codeframe already covers this response column.

    Args:
        db: Session.
        project_id: Project id.
        variable: Response column, or empty when the request did not name one.

    Returns:
        True when coding should use that saved codeframe instead of discovering one.
    """
    revision = ArtifactRepository(db).latest_of_type(project_id, "codeframe")
    if revision is None:
        return False
    payload = revision.content
    if "codeframe" in payload and "codes" not in payload:
        payload = payload["codeframe"]
    saved = str(payload.get("response_variable") or "")
    return not variable or saved.lower() == variable.lower()


async def run_auto_coding(
    db: Session,
    storage: Storage,
    settings: Settings,
    project_id: str,
    fields: dict[str, Any],
    request: str = "",
    on_stage: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Discover a codeframe for one open-end column and code every response.

    Args:
        db: Session.
        storage: Project storage.
        settings: Application settings. The OpenAI key comes from here.
        project_id: Project id.
        fields: Contract fields: response column, question wording, respondent id, weight.
        request: User text, used to find the column when no field names it.
        on_stage: Optional callback for real stage messages.

    Returns:
        Task outcome with the coding artifact id.

    Raises:
        AppError: The AutoCoder is missing, the column or wording cannot be found,
            or the column has no answers.
    """
    if not autocoder_available():
        raise AppError(
            "The Ad Hoc AutoCoder is not installed in this backend. Install it, or ask me to "
            "propose a codeframe for review instead.",
            "unsupported_method",
        )
    dataset = _active_dataset(db, project_id)
    frame = load_frame(storage, dataset)
    variable = resolve_text_variable(fields, request, dataset.variables, list(frame.columns))
    question = question_wording(fields, dataset.variables, variable)
    respondent = respondent_column(fields, list(frame.columns))
    if not settings.openai_api_key.strip():
        raise AppError("The Ad Hoc AutoCoder needs an OpenAI API key.", "missing_key")
    texts = ["" if pd.isna(value) else str(value) for value in frame[variable].tolist()]
    if not any(text.strip() for text in texts):
        raise AppError(f"{variable} has no answers to code.", "small_sample")
    model = settings.model_autocoder
    tag = hashlib.sha256(f"{dataset.id}|{variable}|{question}|{model}".encode()).hexdigest()[:10]
    workdir = storage.resolve(project_id, f"autocoder/{variable}_{tag}")
    workdir.mkdir(parents=True, exist_ok=True)
    source = workdir / "input.xlsx"
    _write_input(source, variable, texts)
    if on_stage is not None:
        on_stage("Discovering a codeframe and coding responses with the Ad Hoc AutoCoder")
    manifest = await _run_pipeline(settings, source, workdir, variable, question)
    codes, results = _read_outputs(workdir)
    codeframe = _codeframe(codes, variable, respondent)
    rows = _assignments(frame, texts, respondent, codeframe, results, model)
    weights = _weight_map(frame, fields, rows)
    report, rows = aggregate_saved_coding(codeframe, rows, weights)
    if on_stage is not None:
        on_stage("Writing the coded data and workbooks")
    file_id = _export(db, storage, project_id, frame, codeframe, rows, report)
    autocoder_file_id = _write_export(
        db,
        storage,
        project_id,
        f"autocoder_{variable}.xlsx",
        (workdir / "output.xlsx").read_bytes(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    codeframe_id = _save_codeframe(db, project_id, codeframe, codes)
    coding_stats = manifest.get("coding") or {}
    artifact_id = _save_coding(
        db,
        project_id,
        codeframe,
        rows,
        report,
        file_id=file_id,
        autocoder_file_id=autocoder_file_id,
        codeframe_artifact_id=codeframe_id,
        charts=coding_chart_files(db, storage, project_id, report, codeframe),
        run={
            "engine": ENGINE,
            "model": model,
            "question_text": question,
            "codeframe_size": len(codes),
            "nets": sorted({code["net"] for code in codes}),
            "coding": {key: value for key, value in coding_stats.items() if key != "checkpoint"},
        },
    )
    from app.engines.invariants import summarize

    gate = summarize(_checks(db, rows, report, storage, file_id))
    review = sum(1 for row in rows if row.review_required and row.substantive)
    nets = len({code["net"] for code in codes})
    summary = (
        f"The Ad Hoc AutoCoder built a codeframe for {variable} with {len(codes)} codes under "
        f"{nets} nets and coded {report.substantive_n} answers. {review} answers are in the "
        f"review queue. Only the question wording and the {variable} answers were sent to "
        f"OpenAI ({model}); respondent ids stayed local."
    )
    status = "completed_with_warnings" if review else "completed"
    if gate.status != "passed":
        status = "failed"
        summary = "Coding did not pass validation. " + summary
    return {
        "summary": summary,
        "status": status,
        "artifact_id": artifact_id,
        "validation": gate.model_dump(mode="json"),
        "warnings": report.warnings,
    }


def resolve_text_variable(
    fields: dict[str, Any], request: str, variables: list[dict[str, Any]], columns: list[str]
) -> str:
    """Return the open-end column to code.

    The named field wins. Otherwise a text column named in the request is used,
    or the only text column in the dataset.

    Raises:
        AppError: No column, or several, could be the one meant.
    """
    lookup = {name.lower(): name for name in columns}
    named = str(fields.get("response_variable") or "").strip()
    if named:
        if named.lower() not in lookup:
            raise AppError(f"{named} is not in the active dataset.", "missing_variable")
        return lookup[named.lower()]
    text_columns = [
        str(item["name"])
        for item in variables
        if item.get("is_text")
        and str(item["name"]) in columns
        and not _NOT_ANSWER.search(str(item.get("label") or ""))
    ]
    mentioned = [
        name for name in text_columns if re.search(rf"\b{re.escape(name)}\b", request, re.I)
    ]
    if len(mentioned) == 1:
        return mentioned[0]
    if len(text_columns) == 1:
        return text_columns[0]
    choices = ", ".join(text_columns[:12]) or "none found"
    raise AppError(
        f"Which open-end column should I code? Text columns: {choices}.",
        "clarification_needed",
    )


def question_wording(fields: dict[str, Any], variables: list[dict[str, Any]], variable: str) -> str:
    """Return the full question wording for the AutoCoder.

    Raises:
        AppError: The label is only the column name, so the wording is unknown.
    """
    given = str(fields.get("question_text") or "").strip()
    if given:
        return given
    info = next((item for item in variables if str(item.get("name")) == variable), {})
    label = _LABEL_PREFIX.sub("", str(info.get("label") or "")).strip()
    if not label or label.lower() == variable.lower():
        raise AppError(
            f"I need the full question wording for {variable}. Reply with: "
            f'code {variable}, question "…".',
            "clarification_needed",
        )
    return label


def respondent_column(fields: dict[str, Any], columns: list[str]) -> str:
    """Return the respondent id column, or empty to number rows instead."""
    lookup = {name.lower(): name for name in columns}
    named = str(fields.get("respondent_id_variable") or "").lower()
    if named in lookup:
        return lookup[named]
    return next((lookup[name] for name in _ID_NAMES if name in lookup), "")


def _write_input(path: Path, variable: str, texts: list[str]) -> None:
    """Write the AutoCoder input sheet with row numbers, not respondent ids."""
    book = Workbook()
    sheet = book.active
    sheet.title = "Coded data"
    sheet.append(["record", variable])
    for position, text in enumerate(texts):
        sheet.append([position + 1, text])
    book.save(path)


async def _run_pipeline(
    settings: Settings, source: Path, workdir: Path, variable: str, question: str
) -> dict[str, Any]:
    """Run the AutoCoder pipeline. A rerun in the same folder resumes from its checkpoints."""
    from adhoc_autocoder.config import Config, EmbeddingConfig, InputConfig, LLMConfig
    from adhoc_autocoder.pipeline import run

    embeddings = settings.autocoder_embeddings
    if (
        embeddings == "sentence_transformers"
        and importlib.util.find_spec("sentence_transformers") is None
    ):
        embeddings = "tfidf"
    config = Config(
        input=InputConfig(sheet_name="Coded data", id_columns=["record"]),
        embeddings=EmbeddingConfig(provider=embeddings),
        llm=LLMConfig(
            model=settings.model_autocoder, max_concurrency=settings.autocoder_concurrency
        ),
    )
    try:
        return await run(
            source,
            workdir / "output.xlsx",
            variable,
            question,
            config,
            workdir=workdir,
            llm_factory=_llm_factory(settings),
        )
    except AppError:
        raise
    except Exception as error:
        raise AppError(f"The Ad Hoc AutoCoder stopped: {error}", "model_failed") from error


def _llm_factory(settings: Settings) -> type:
    """Return the AutoCoder LLM class with the key from settings, not the environment."""
    from adhoc_autocoder.llm import LLM
    from openai import AsyncOpenAI

    class _SettingsKeyLLM(LLM):
        def __init__(self, conf: Any, cache_dir: Path) -> None:
            self.client = AsyncOpenAI(
                api_key=settings.openai_api_key,
                timeout=conf.request_timeout_seconds,
                max_retries=1,
            )
            self.settings = conf
            self.semaphore = asyncio.Semaphore(conf.max_concurrency)
            self.cache_dir = cache_dir
            cache_dir.mkdir(parents=True, exist_ok=True)

    return _SettingsKeyLLM


def _read_outputs(workdir: Path) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    """Read the saved codeframe and the last result per row from the checkpoint."""
    book = workdir / "codeframe.json"
    if not book.exists():
        raise AppError("The Ad Hoc AutoCoder did not produce a codeframe.", "model_failed")
    codes = json.loads(book.read_text(encoding="utf-8"))["codes"]
    results: dict[int, dict[str, Any]] = {}
    checkpoint = workdir / "labeling_checkpoint.jsonl"
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding="utf-8").splitlines():
            if line.strip():
                result = json.loads(line)["result"]
                results[int(result["row_index"])] = result
    return codes, results


def _codeframe(codes: list[dict[str, Any]], variable: str, respondent: str) -> Codeframe:
    """Convert AutoCoder leaf codes into a studio codeframe with NET and SUBNET rollups."""
    nodes = [
        CodeNode(
            id=str(code["code_id"]),
            label=str(code["code_name"]),
            value=index + 1,
            definition=str(code.get("definition") or ""),
            include_examples=[text for text in [code.get("include")] if text]
            + list(code.get("examples") or [])[:3],
            exclude_examples=[text for text in [code.get("exclude")] if text],
        )
        for index, code in enumerate(codes)
    ]
    nets: list[NetNode] = []
    groups: dict[str, list[str]] = {}
    subgroups: dict[tuple[str, str], list[str]] = {}
    for code in codes:
        groups.setdefault(str(code["net"]), []).append(str(code["code_id"]))
        subnet = str(code.get("subnet") or "")
        if subnet and subnet != code["net"]:
            subgroups.setdefault((str(code["net"]), subnet), []).append(str(code["code_id"]))
    for index, (net, children) in enumerate(groups.items(), start=1):
        nets.append(NetNode(id=f"NET{index}", label=net, child_ids=children))
        position = 1
        for (parent, subnet), members in subgroups.items():
            if parent == net:
                nets.append(
                    NetNode(
                        id=f"NET{index}_{position}", label=f"{net} > {subnet}", child_ids=members
                    )
                )
                position += 1
    return Codeframe(
        codeframe_id=new_id(),
        response_variable=variable,
        respondent_id_variable=respondent or "row",
        codes=nodes,
        nets=nets,
    )


def _assignments(
    frame: pd.DataFrame,
    texts: list[str],
    respondent: str,
    codeframe: Codeframe,
    results: dict[int, dict[str, Any]],
    model: str,
) -> list[CodingAssignment]:
    """One assignment per dataset row. Rows the AutoCoder could not code go to review."""
    known = {code.id for code in codeframe.codes}
    rows: list[CodingAssignment] = []
    for position, text in enumerate(texts):
        respondent_id = (
            _id_text(frame.iloc[position][respondent]) if respondent else str(position + 1)
        )
        substantive = not _blank(text, codeframe.placeholders)
        result = results.get(position) or {}
        codes = [code for code in result.get("assigned_codes") or [] if code in known]
        review = bool(result.get("review_required")) or (substantive and not result)
        reason = " ".join(
            part
            for part in (
                str(result.get("review_category") or ""),
                str(result.get("review_reason") or ""),
            )
            if part
        )
        if substantive and not result:
            reason = "The AutoCoder returned no result for this row."
        rows.append(
            CodingAssignment(
                respondent_id=respondent_id,
                source_row_id=position,
                response_text=text,
                assigned_code_ids=codes if substantive else [],
                review_required=review and substantive,
                review_reason=reason or None,
                model_version=f"{ENGINE} / {model}",
                substantive=substantive,
            )
        )
    return rows


def _id_text(value: Any) -> str:
    """Return a respondent id as text, without a trailing .0 from SPSS numerics."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _weight_map(
    frame: pd.DataFrame, fields: dict[str, Any], rows: list[CodingAssignment]
) -> dict[str, float] | None:
    """Weights keyed the same way as the assignments, when the request names a weight."""
    name = str(fields.get("weight_variable") or "")
    if not name or name not in frame.columns:
        return None
    weights: dict[str, float] = {}
    for row in rows:
        value = frame.iloc[row.source_row_id][name]
        if not pd.isna(value):
            weights[row.respondent_id] = float(value)
    return weights


def _save_codeframe(
    db: Session, project_id: str, codeframe: Codeframe, codes: list[dict[str, Any]]
) -> str:
    """Save the discovered codeframe as its own artifact for this column."""
    name = f"Codeframe {codeframe.response_variable} (AutoCoder)"
    existing = db.scalar(
        select(Artifact).where(
            Artifact.project_id == project_id, Artifact.type == "codeframe", Artifact.name == name
        )
    )
    content = codeframe.model_dump(mode="json")
    content["engine"] = ENGINE
    content["hierarchy"] = [
        {key: code.get(key) for key in ("code_id", "net", "subnet", "subsubnet", "code_name")}
        for code in codes
    ]
    revision = ArtifactRepository(db).create(
        project_id=project_id,
        artifact_type="codeframe",
        name=name,
        content=content,
        content_schema="codeframe/1",
        created_by="coding",
        artifact_id=existing.id if existing else None,
        validation_status="needs_review",
    )
    return revision.artifact_id


def _save_coding(
    db: Session,
    project_id: str,
    codeframe: Codeframe,
    rows: list[CodingAssignment],
    report: CodingReport,
    *,
    file_id: str,
    autocoder_file_id: str,
    codeframe_artifact_id: str,
    run: dict[str, Any],
    charts: dict[str, Any],
) -> str:
    """Save the coding artifact, including the AutoCoder run details and its workbook."""
    name = f"Coding {codeframe.response_variable} (AutoCoder)"
    existing = db.scalar(
        select(Artifact).where(
            Artifact.project_id == project_id, Artifact.type == "coding", Artifact.name == name
        )
    )
    revision = ArtifactRepository(db).create(
        project_id=project_id,
        artifact_type="coding",
        name=name,
        content={
            "codeframe_id": codeframe.codeframe_id,
            "codeframe_artifact_id": codeframe_artifact_id,
            "response_variable": codeframe.response_variable,
            "assignments": [row.model_dump(mode="json") for row in rows],
            "report": report.model_dump(mode="json"),
            "export_file_id": file_id,
            "autocoder_file_id": autocoder_file_id,
            **charts,
            "autocoder": run,
            "disclosure": (
                "Only the question wording and the selected answers were sent to OpenAI by the "
                "Ad Hoc AutoCoder, with row numbers instead of respondent ids."
            ),
        },
        content_schema="coding/1",
        created_by="coding",
        artifact_id=existing.id if existing else None,
        validation_status="pending",
    )
    return revision.artifact_id
