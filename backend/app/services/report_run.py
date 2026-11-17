"""Execute the report plan: compute every slide through the right agent, write it, and build the PPTX."""

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.report_writer import write_slides, write_takeaways
from app.config import Settings
from app.engines.analysis.steps import mask_off_scale, mask_user_missing
from app.engines.report.compute import Labels, compute_slide
from app.engines.report.pptx_build import build_deck
from app.errors import AppError
from app.models.tables import Artifact, ArtifactRevision, Dataset
from app.repositories.records import ArtifactRepository, ProjectRepository
from app.schemas.questionnaire import Questionnaire
from app.schemas.report_plan import PlanSlide, ReportPlan
from app.services.execute import load_frame
from app.services.report_plan_run import load_plan, plan_with_data, refresh_plan, save_plan
from app.services.storage import Storage
from app.services.stored_files import _write_export

logger = logging.getLogger(__name__)
_PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_COMPUTED = {
    "distribution",
    "profile",
    "grid_summary",
    "mean_summary",
    "nps",
    "rank_summary",
    "funnel",
}


async def run_report(
    db: Session,
    storage: Storage,
    settings: Settings,
    project_id: str,
    conversation_id: str,
    on_stage: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run the saved plan end to end and publish the deck.

    Missing steps are done first: no plan drafts one, and data that has not been
    cleaned and fitted goes through the data stage.

    Returns:
        Task outcome with the report artifact.
    """
    stage = on_stage or (lambda _m: None)
    session_id = ProjectRepository(db).conversation(conversation_id).sdk_session_id
    if load_plan(db, project_id) is None:
        stage("Drafting the report plan")
        await refresh_plan(db, settings, project_id, session_id=session_id, storage=storage)
    project = ProjectRepository(db).get(project_id)
    plan = load_plan(db, project_id)
    if (
        plan.stage not in {"data_ready", "reported"}
        or plan.data.dataset_id != project.active_dataset_id
    ):
        await plan_with_data(db, storage, settings, project_id, conversation_id, on_stage)
        plan = load_plan(db, project_id)
        project = ProjectRepository(db).get(project_id)
    dataset = db.get(Dataset, project.active_dataset_id)
    if dataset is None:
        raise AppError("Upload the survey data first.", "missing_dataset")
    frame = load_frame(storage, dataset)
    variables = list(dataset.variables or [])
    data = mask_user_missing(frame, variables)
    data, _ = mask_off_scale(data, variables)
    labels = Labels(variables)
    questionnaire = _questionnaire(db, project_id)
    results: dict[str, dict[str, Any]] = {}
    skipped: list[list[str]] = []
    slides = [s for s in plan.all_slides() if s.kind not in {"title", "text"}]
    for index, slide in enumerate(slides, start=1):
        if slide.status in {"dropped", "needs_data", "low_base"}:
            skipped.append([slide.title, slide.status_reason or slide.status])
            continue
        stage(f"Slide {index} of {len(slides)}: {slide.title}")
        try:
            if slide.kind in _COMPUTED:
                results[slide.id] = compute_slide(slide, data, labels, plan.data.weight_variable)
            elif slide.kind == "analysis":
                results[slide.id] = await _analysis(
                    db, storage, settings, project_id, slide, session_id, stage
                )
            elif slide.kind == "coding":
                results[slide.id] = await _coding(db, storage, settings, project_id, slide)
            slide.status = "done"
            slide.status_reason = ""
        except Exception as error:
            logger.warning("Slide %s failed", slide.id, exc_info=True)
            slide.status = "failed"
            slide.status_reason = str(getattr(error, "message", error))[:300]
            skipped.append([slide.title, slide.status_reason])
    stage("Writing headlines from the computed numbers")
    packs = [
        {
            "slide_id": s.id,
            "kind": s.kind,
            "title": s.title,
            "purpose": s.purpose,
            "facts": results[s.id]["facts"][:40],
        }
        for s in slides
        if s.id in results
    ]
    texts = await write_slides(settings, packs, session_id)
    headlines = [
        {"slide_id": s.id, "objective_ids": s.objective_ids, "headline": texts[s.id]["headline"]}
        for s in slides
        if s.id in texts
    ]
    takeaways = await write_takeaways(
        settings, [o.model_dump() for o in plan.objectives], headlines, session_id
    )
    stage("Building the PowerPoint deck")
    deck = _deck(plan, results, texts, takeaways, skipped, questionnaire)
    file_id = _write_export(db, storage, project_id, "report.pptx", build_deck(deck), _PPTX)
    plan.stage = "reported"
    save_plan(db, project_id, plan)
    revision = _save_report(db, project_id, plan, deck, file_id, skipped)
    built = sum(1 for s in deck["slides"] if s["type"] in {"chart", "table"})
    summary = (
        f"Built the report: {len(deck['slides'])} slides, {built} with charts or tables, in story order from "
        f"objectives and sample to insights and takeaways. Every chart is a native PowerPoint chart you can edit. "
        f"{len(skipped)} planned slides were not included; the appendix lists why."
    )
    return {
        "summary": summary,
        "status": "completed_with_warnings" if skipped else "completed",
        "artifact_id": revision.artifact_id,
        "version": revision.version,
    }


_UNATTENDED = (
    "This analysis runs unattended inside report generation, so nobody can answer questions. "
    "Do not ask for clarification: choose the standard quant market research default for any "
    "open choice and state it as an assumption. Defaults: treat don't know, not applicable and "
    "codes 97-99 as missing; band ages 18-34, 35-54, 55+; keep numeric counts such as household "
    "size as 1, 2, 3, 4+; for brand-level ratings use respondents aware of that brand where an "
    "awareness question exists, otherwise all who answered; for overlapping groups such as "
    "multi-brand owners, compare each group against everyone not in it."
)


def unattended_request(slide: PlanSlide) -> str:
    """The slide's analysis request, with its variables and defaults so the analyst need not ask."""
    request = slide.source.analysis_request or slide.purpose or slide.title
    parts = [request.strip()]
    if slide.source.variables:
        parts.append("Use these variables: " + ", ".join(slide.source.variables[:40]) + ".")
    if slide.source.filter:
        parts.append(f"Base: respondents where {slide.source.filter}.")
    if _pair_method(slide) and len(slide.source.variables) > 2:
        parts.append(_GRID_NOTE)
    parts.append(_UNATTENDED)
    return "\n".join(parts)


_PAIR_METHODS = {"chi_square", "correspondence"}
_GRID_NOTE = (
    "The built-in chi-square and correspondence procedures cross exactly two columns. This "
    "request spans several columns, so do not use them: treat it as a custom procedure (for "
    "example stack the brand by attribute grid into one table of brand rows and attribute "
    "columns, or test each group variable against the outcome in turn) and report one table."
)


def _pair_method(slide: PlanSlide) -> bool:
    return (slide.source.method or "").lower() in _PAIR_METHODS


async def _analysis(
    db: Session,
    storage: Storage,
    settings: Settings,
    project_id: str,
    slide: PlanSlide,
    session_id: str,
    stage: Callable[[str], None],
) -> dict[str, Any]:
    """Ask the analysis agent for the slide's analysis and turn its result into a chart and facts."""
    from app.services.analysis_run import run_planned_analysis

    request = unattended_request(slide)
    grid = _pair_method(slide) and len(slide.source.variables) > 2
    hints = {"method": slide.source.method} if slide.source.method and not grid else {}

    async def attempt(text: str) -> dict[str, Any]:
        return await run_planned_analysis(
            db,
            storage,
            settings,
            project_id,
            request=text,
            hints=hints,
            session_id=session_id,
            on_stage=lambda message: stage(f"{slide.title}: {message}"),
        )

    try:
        outcome = await attempt(request)
    except AppError as error:
        if "needs these fields" in str(error) and "var_a" in str(error):
            stage(f"{slide.title}: rewriting it as a custom analysis")
            hints = {}
            outcome = await attempt(f"{request}\n{_GRID_NOTE}")
        elif error.code == "clarification_needed":
            stage(f"{slide.title}: applying standard defaults to the open choices")
            outcome = await attempt(
                f"{request}\nThe analyst asked: {str(error)[:800]}\n"
                "Nobody can answer during report generation. Take the default you proposed for "
                "each choice (or the standard market research default) and run the analysis now."
            )
        else:
            raise
    content = _latest_content(db, outcome["artifact_id"])
    result = content.get("result") or {}
    specs = content.get("chart_specs") or []
    chart = spec_to_chart(specs[0]) if specs else None
    facts = _analysis_facts(result)
    checks = (result.get("diagnostics") or {}).get("quality_checks") or []
    flags = [f"{c.get('check')}: {c.get('detail')}" for c in checks if c.get("status") == "flag"][
        :2
    ]
    base = (result.get("sample_flow") or {}).get("valid_n")
    return {
        "chart": chart,
        "facts": facts,
        "base_n": base,
        "base_text": f"Base: analysis sample (n={base}); {content.get('workflow', {}).get('objective', '')[:120]}",
        "notes": "\n".join(flags),
        "extra_charts": [
            {**spec_to_chart(spec), "title": spec.get("title", "")} for spec in specs[1:3]
        ],
    }


async def _coding(
    db: Session, storage: Storage, settings: Settings, project_id: str, slide: PlanSlide
) -> dict[str, Any]:
    """Reuse the coded open end, or run the AutoCoder, then chart the most mentioned codes."""
    variable = (slide.source.variables or [""])[0]
    content = _coding_for(db, project_id, variable)
    if content is None:
        from app.services.autocode_run import autocoder_available, run_auto_coding

        if not autocoder_available() or not settings.openai_api_key.strip():
            raise AppError(
                f"No coded result for {variable}, and the AutoCoder is not available.",
                "unsupported_method",
            )
        outcome = await run_auto_coding(
            db, storage, settings, project_id, {"response_variable": variable}
        )
        content = _latest_content(db, outcome["artifact_id"])
    report = content.get("report") or {}
    codes = sorted(
        (
            f
            for f in report.get("frequencies") or []
            if f.get("kind") == "code" and f.get("pct_of_respondents") is not None
        ),
        key=lambda f: -f["pct_of_respondents"],
    )[:10]
    nets = sorted(
        (
            f
            for f in report.get("frequencies") or []
            if f.get("kind") == "net" and f.get("pct_of_respondents") is not None
        ),
        key=lambda f: -f["pct_of_respondents"],
    )[:6]
    chart = {
        "kind": "bar",
        "categories": [str(f["label"]).replace("_", " ").capitalize() for f in codes],
        "series": [
            {"name": "% of respondents", "values": [round(f["pct_of_respondents"]) for f in codes]}
        ],
        "number_format": "pct",
    }
    facts = [
        {"label": f"{f['label']} (net)", "value": round(f["pct_of_respondents"]), "unit": "%"}
        for f in nets
    ]
    facts += [
        {"label": f["label"], "value": round(f["pct_of_respondents"]), "unit": "%"} for f in codes
    ]
    top = {c.get("id") for c in codes[:1]}
    quotes = [
        row.get("response_text")
        for row in content.get("assignments") or []
        if top & set(row.get("assigned_code_ids") or [])
        and 20 <= len(row.get("response_text") or "") <= 160
    ][:2]
    return {
        "chart": chart,
        "facts": facts,
        "base_n": report.get("substantive_n"),
        "base_text": f"Base: respondents who answered {variable} (n={report.get('substantive_n')}); coded open end",
        "quotes": quotes,
    }


def spec_to_chart(spec: dict[str, Any]) -> dict[str, Any]:
    """Turn an analysis chart spec into the deck's native chart description."""
    kind = spec.get("kind")
    if kind == "heatmap":
        return {
            "kind": "table",
            "table": {
                "columns": ["", *spec.get("columns", [])],
                "rows": [
                    [r, *row]
                    for r, row in zip(spec.get("rows", []), spec.get("matrix", []), strict=False)
                ],
            },
        }
    if kind == "line":
        return {
            "kind": "xy",
            "series": [
                {"name": s.get("name"), "x": s.get("x"), "y": s.get("y")}
                for s in spec.get("series", [])
            ],
        }
    mapped = {"barh": "bar", "bar": "column", "stacked_bar": "stacked_column"}.get(kind, "bar")
    return {
        "kind": mapped,
        "categories": spec.get("categories", []),
        "series": [
            {"name": s.get("name") or spec.get("title", ""), "values": s.get("values", [])}
            for s in spec.get("series", [])
        ],
        "number_format": "number",
    }


def _analysis_facts(result: dict[str, Any]) -> list[dict[str, Any]]:
    facts = []
    for key, value in (result.get("metrics") or {}).items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            facts.append(
                {"label": key.replace("_", " "), "value": round(float(value), 3), "unit": ""}
            )
    descriptive = result.get("descriptive") or {}
    ranking = descriptive.get("importance_ranking") or []
    for row in ranking[:6]:
        facts.append(
            {
                "label": f"{row['driver']} importance",
                "value": round(row["importance_pct"], 1),
                "unit": "%",
            }
        )
    sizes = (result.get("model_estimates") or {}).get("sizes")
    if isinstance(sizes, dict):
        total = sum(sizes.values()) or 1
        for name, n in sizes.items():
            facts.append(
                {"label": f"Segment {name} size", "value": round(100 * n / total), "unit": "%"}
            )
    return facts[:40]


def _deck(
    plan: ReportPlan,
    results: dict[str, dict[str, Any]],
    texts: dict[str, dict[str, Any]],
    takeaways: list[str],
    skipped: list[list[str]],
    questionnaire: Questionnaire | None,
) -> dict[str, Any]:
    """Lay the computed slides out in storyline order with section dividers."""
    facts = plan.data
    slides: list[dict[str, Any]] = []
    number = 0
    for section in plan.sections:
        live = [s for s in section.slides if s.status != "dropped"]
        content_slides = [s for s in live if s.kind in {"title", "text"} or s.id in results]
        if not content_slides:
            continue
        if section.id not in {"sec-intro"}:
            number += 1
            slides.append(
                {
                    "type": "section",
                    "number": number,
                    "title": section.title,
                    "subtitle": section.purpose[:200],
                }
            )
        for slide in content_slides:
            if slide.kind == "title":
                slides.append({"type": "title", "title": plan.title, "subtitle": "Study findings"})
            elif slide.id == "objectives":
                slides.append(
                    {
                        "type": "text",
                        "title": slide.title,
                        "bullets": [o.text for o in plan.objectives],
                    }
                )
            elif slide.id == "approach":
                slides.append(
                    {
                        "type": "text",
                        "title": slide.title,
                        "bullets": _approach(plan, questionnaire),
                    }
                )
            elif slide.id == "takeaways":
                slides.append({"type": "text", "title": "Key takeaways", "bullets": takeaways})
            elif slide.id == "appendix-bases":
                rows = [
                    [s.title[:70], s.base_n if s.base_n is not None else "", s.status]
                    for s in plan.all_slides()
                    if s.kind not in {"title", "text"}
                ]
                slides.append(
                    {
                        "type": "table",
                        "title": "Base sizes",
                        "table": {"columns": ["Slide", "Base (n)", "Status"], "rows": rows[:22]},
                    }
                )
                if skipped:
                    slides.append(
                        {
                            "type": "table",
                            "title": "Planned slides not included",
                            "table": {"columns": ["Slide", "Reason"], "rows": skipped[:18]},
                        }
                    )
            elif slide.kind == "text":
                slides.append(
                    {
                        "type": "text",
                        "title": slide.title,
                        "bullets": [slide.purpose] if slide.purpose else [],
                    }
                )
            else:
                result = results[slide.id]
                text = texts.get(slide.id) or {"headline": slide.title, "bullets": []}
                bullets = list(text["bullets"]) + [f'"{q}"' for q in result.get("quotes") or []]
                chart = result.get("chart")
                if result.get("table") and not chart:
                    chart = {"kind": "table", "table": result["table"]}
                slides.append(
                    {
                        "type": "chart" if chart else "text",
                        "title": text["headline"],
                        "subtitle": f"{slide.title}. {slide.purpose}"[:220],
                        "chart": chart,
                        "bullets": bullets[:4],
                        "base_text": result.get("base_text", ""),
                        "notes": result.get("notes", ""),
                    }
                )
                for extra in result.get("extra_charts") or []:
                    slides.append(
                        {
                            "type": "chart",
                            "title": extra.get("title") or f"{slide.title}: detail",
                            "chart": extra,
                            "base_text": result.get("base_text", ""),
                        }
                    )
    del facts
    return {"title": plan.title, "subtitle": "Study findings", "slides": slides}


def _approach(plan: ReportPlan, questionnaire: Questionnaire | None) -> list[str]:
    facts = plan.data
    lines = []
    if facts.final_n is not None:
        lines.append(
            f"Online survey, {facts.final_n} respondents in the final sample{' (' + plan.audience + ')' if plan.audience else ''}."
        )
    if facts.removed_by_cleaning:
        lines.append(
            f"{facts.removed_by_cleaning} of {facts.raw_n} completes were removed in data cleaning (speeding, straight-lining, fraud checks)."
        )
    if questionnaire is not None:
        minutes = (
            f", about {questionnaire.estimated_minutes:g} minutes"
            if questionnaire.estimated_minutes
            else ""
        )
        lines.append(f"Questionnaire of {len(questionnaire.questions)} questions{minutes}.")
    lines.append(
        f"Results are {'weighted by ' + facts.weight_variable if facts.weight_variable else 'unweighted'}."
    )
    lines.append(
        "'Don't know' answers are excluded from scale scores. Bases under 30 are not reported; bases under 50 are directional."
    )
    return lines


def _save_report(
    db: Session,
    project_id: str,
    plan: ReportPlan,
    deck: dict[str, Any],
    file_id: str,
    skipped: list[list[str]],
) -> Any:
    repo = ArtifactRepository(db)
    existing = repo.latest_of_type(project_id, "report")
    return repo.create(
        project_id=project_id,
        artifact_type="report",
        name=f"Report: {plan.title}"[:200],
        content={
            "title": plan.title,
            "export_file_id": file_id,
            "slides": [
                {
                    "type": s["type"],
                    "title": s.get("title", ""),
                    "subtitle": s.get("subtitle", ""),
                    "bullets": s.get("bullets", []),
                }
                for s in deck["slides"]
            ],
            "skipped": skipped,
        },
        content_schema="report/1",
        created_by="report_planner",
        artifact_id=existing.artifact_id if existing else None,
        validation_status="passed",
    )


def _questionnaire(db: Session, project_id: str) -> Questionnaire | None:
    revision = ArtifactRepository(db).latest_of_type(project_id, "questionnaire")
    return Questionnaire.model_validate(revision.content) if revision else None


def _latest_content(db: Session, artifact_id: str) -> dict[str, Any]:
    row = db.scalar(
        select(ArtifactRevision)
        .where(ArtifactRevision.artifact_id == artifact_id)
        .order_by(ArtifactRevision.version.desc())
        .limit(1)
    )
    return dict(row.content or {}) if row else {}


def _coding_for(db: Session, project_id: str, variable: str) -> dict[str, Any] | None:
    rows = db.scalars(
        select(Artifact).where(Artifact.project_id == project_id, Artifact.type == "coding")
    ).all()
    for artifact in sorted(rows, key=lambda a: a.updated_at, reverse=True):
        content = _latest_content(db, artifact.id)
        if str(content.get("response_variable") or "").lower() == variable.lower():
            return content
    return None
