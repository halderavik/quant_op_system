"""Draft a report plan from the questionnaire, check coverage, and merge with user edits.

Everything here is deterministic, so a plan exists even without a model key. The
planner agent only refines titles, order, and adds analysis on top of this draft.
"""

import re
from typing import Any

from app.engines.offscale import is_off_scale_label
from app.schemas.questionnaire import Question, Questionnaire
from app.schemas.report_plan import (
    CoverageRow,
    Objective,
    PlanSection,
    PlanSlide,
    ReportPlan,
    SlideSource,
)

_DEMOGRAPHIC = re.compile(
    r"\bage\b|gender|region|income|household|children|employ|education|ethnic|marital|state\b|zip|"
    r"how old|live in|profile",
    re.I,
)
_ATTENTION = re.compile(r"attention|for this question only|please select", re.I)
_SUPPORT = re.compile(r"^\s*support analysis|subgroup|\bby gender\b|analysis by", re.I)
_OUTCOME = re.compile(r"recommend|satisf|likely to (buy|purchase)|purchase intent|nps", re.I)
_FUNNEL_WORDS = ("aware", "consider", "purchase", "own")


def draft_plan(questionnaire: Questionnaire, study: dict[str, Any] | None = None) -> ReportPlan:
    """Build the full storyline from the questionnaire alone.

    Args:
        questionnaire: The current questionnaire.
        study: Project study context (objectives, audience).

    Returns:
        A plan with every reportable question placed and coverage filled in.
    """
    study = study or {}
    questions = {q.id: q for q in questionnaire.questions}
    module_of = {qid: m.title for m in questionnaire.modules for qid in m.question_ids}
    objectives = [
        Objective(id=o.id, text=o.description, question_ids=list(o.question_ids))
        for o in questionnaire.objectives
    ] or [
        Objective(id=f"O{index + 1}", text=str(text))
        for index, text in enumerate(study.get("objectives") or [])
    ]
    placed: set[str] = set()
    sections: list[PlanSection] = [
        PlanSection(
            id="sec-intro",
            title="Objectives and approach",
            purpose="Why the study was run and how.",
            slides=[
                PlanSlide(id="title", kind="title", title=questionnaire.title, chart="none"),
                PlanSlide(
                    id="objectives",
                    kind="text",
                    title="What this study set out to answer",
                    purpose="The study objectives, in the client's words.",
                    chart="none",
                ),
                PlanSlide(
                    id="approach",
                    kind="text",
                    title="Approach and sample",
                    purpose="Method, sample size, fieldwork, cleaning and weighting.",
                    chart="none",
                ),
            ],
        )
    ]
    profile = [
        q
        for q in questionnaire.questions
        if _is_profile(q, module_of.get(q.id, "")) and not _skip_reason(q)
    ]
    sections.append(
        PlanSection(
            id="sec-sample",
            title="Who we spoke to",
            purpose="Sample profile and data exploration before any insight.",
            slides=[_profile_slide(q) for q in profile],
        )
    )
    placed.update(q.id for q in profile)
    support = [o for o in objectives if _SUPPORT.search(o.text)]
    for objective in objectives:
        if objective in support:
            continue
        slides: list[PlanSlide] = []
        funnel = _funnel(objective, questions)
        if funnel:
            slides.append(funnel)
        for qid in objective.question_ids:
            question = questions.get(qid)
            if question is None or qid in placed or _skip_reason(question):
                continue
            slides.extend(_question_slides(question, objective.id))
            placed.add(qid)
        if slides:
            sections.append(
                PlanSection(
                    id=f"sec-{objective.id.lower()}",
                    title=_short(objective.text),
                    purpose=objective.text,
                    slides=slides,
                )
            )
    deep = _analysis_slides(questionnaire, objectives)
    banners = _banner_variables(questionnaire, support)
    groups = _group_slides(questionnaire, banners, support)
    if groups:
        sections.append(
            PlanSection(
                id="sec-groups",
                title="Differences across groups",
                purpose="Where the key measures differ by subgroup.",
                slides=groups,
            )
        )
    if deep:
        sections.append(
            PlanSection(
                id="sec-deep",
                title="What drives the results",
                purpose="Advanced analysis that explains the patterns.",
                slides=deep,
            )
        )
    leftovers = [
        q
        for q in questionnaire.questions
        if q.id not in placed
        and not _skip_reason(q)
        and not _is_profile(q, module_of.get(q.id, ""))
    ]
    if leftovers:
        sections.append(
            PlanSection(
                id="sec-more",
                title="Further findings",
                purpose="Questions that no objective names, so nothing collected goes unreported.",
                slides=[s for q in leftovers for s in _question_slides(q, "")],
            )
        )
    sections.append(
        PlanSection(
            id="sec-close",
            title="Key takeaways",
            purpose="What the findings mean for each objective.",
            slides=[
                PlanSlide(
                    id="takeaways",
                    kind="text",
                    title="Key takeaways",
                    purpose="One takeaway per objective, written from the computed results.",
                    objective_ids=[o.id for o in objectives],
                    chart="none",
                )
            ],
        )
    )
    sections.append(
        PlanSection(
            id="sec-appendix",
            title="Appendix",
            purpose="Method detail and base sizes.",
            slides=[
                PlanSlide(
                    id="appendix-bases",
                    kind="text",
                    title="Base sizes and method notes",
                    purpose="Bases for every slide, cleaning and weighting.",
                    chart="table",
                )
            ],
        )
    )
    plan = ReportPlan(
        title=questionnaire.title,
        audience=str(study.get("audience") or ""),
        objectives=objectives,
        sections=sections,
    )
    plan.coverage = coverage(plan, questionnaire)
    return plan


def coverage(plan: ReportPlan, questionnaire: Questionnaire) -> list[CoverageRow]:
    """Where each question is reported, or why it is not."""
    used: dict[str, list[str]] = {}
    for slide in plan.all_slides():
        if slide.status == "dropped":
            continue
        for qid in slide.source.question_ids:
            used.setdefault(qid, []).append(slide.id)
    rows = []
    for question in questionnaire.questions:
        slides = used.get(question.id, [])
        reason = "" if slides else (_skip_reason(question) or "Not placed on any slide yet.")
        rows.append(
            CoverageRow(
                question_id=question.id, text=question.text[:160], slide_ids=slides, reason=reason
            )
        )
    return rows


def merge(new: ReportPlan, old: ReportPlan | None) -> ReportPlan:
    """Keep what the user changed; take the new draft for everything else.

    User-added and user-edited slides and sections are kept. Slides the user
    removed stay removed. Data facts and stage carry over.
    """
    if old is None:
        return new
    removed = set(old.removed_slide_ids)
    old_slides = {s.id: (sec.id, s) for sec in old.sections for s in sec.slides}
    old_sections = {sec.id: sec for sec in old.sections}
    sections: list[PlanSection] = []
    seen: set[str] = set()
    for section in new.sections:
        prior = old_sections.get(section.id)
        if prior is not None and prior.edited:
            section = section.model_copy(
                update={"title": prior.title, "purpose": prior.purpose, "edited": True}
            )
        slides = []
        for slide in section.slides:
            kept = old_slides.get(slide.id)
            if slide.id in removed:
                # Reason: a removed slide stays visible as removed, so the user can restore it.
                slides.append((kept[1] if kept else slide).model_copy(update={"status": "dropped"}))
                seen.add(slide.id)
                continue
            slides.append(
                kept[1] if kept and (kept[1].edited or kept[1].origin == "user") else slide
            )
            seen.add(slide.id)
        for sid, (sec_id, slide) in old_slides.items():
            if sec_id == section.id and slide.origin == "user" and sid not in seen:
                slides.append(slide)
                seen.add(sid)
        sections.append(section.model_copy(update={"slides": slides}))
    known = {sec.id for sec in sections}
    for section in old.sections:
        if section.id in known:
            continue
        extra = [s for s in section.slides if (s.origin == "user" or s.edited) and s.id not in seen]
        if section.origin == "user" or extra:
            sections.insert(max(len(sections) - 2, 0), section.model_copy(update={"slides": extra}))
    return new.model_copy(
        update={
            "sections": sections,
            "removed_slide_ids": sorted(removed),
            "data": old.data,
            "cleaning": old.cleaning,
            "stage": old.stage if _rank(old.stage) > _rank(new.stage) else new.stage,
            "audience": old.audience or new.audience,
        }
    )


def variables_of(question: Question) -> list[str]:
    """The dataset columns a question's chart reads, without hidden helper variables."""
    names = list(question.variable_names or [question.id])
    own = [name for name in names if re.fullmatch(rf"{re.escape(question.id)}(r\d+)?", name)]
    return own or names[:1]


def _rank(stage: str) -> int:
    return ["draft", "questionnaire_final", "data_ready", "reported"].index(stage)


def _skip_reason(question: Question) -> str:
    """Why a question is not reported, or empty when it should be."""
    stats = " ".join(question.reporting.stats)
    if _ATTENTION.search(question.text) or _ATTENTION.search(stats):
        return "Attention check: used for data quality, not reported."
    if question.type in {"display", "terminate"}:
        return "Display or termination point: no answers to report."
    if question.type == "screener" and len(question.options) <= 2:
        return "Eligibility screener: everyone in the data passed it."
    return ""


def _is_profile(question: Question, module: str) -> bool:
    if question.type in {"matrix", "grid", "text", "rank"}:
        return False
    if question.id.upper().startswith("S"):
        return True
    return bool(_DEMOGRAPHIC.search(question.text) or _DEMOGRAPHIC.search(module))


def _profile_slide(question: Question) -> PlanSlide:
    # Reason: the raw answer is what the data always holds; a numeric one is banded when charted.
    own = variables_of(question)
    return PlanSlide(
        id=f"profile-{question.id}",
        kind="profile",
        title=_title(question),
        purpose=question.text,
        source=SlideSource(
            question_ids=[question.id],
            variables=own if question.type == "multi_select" else own[:1],
        ),
        chart="bar",
    )


def _question_slides(question: Question, objective_id: str) -> list[PlanSlide]:
    """One or two slides for a question, chosen by its type and answer scale."""
    names = variables_of(question)
    base = {"objective_ids": [objective_id] if objective_id else [], "purpose": question.text}
    src = {"question_ids": [question.id], "variables": names}
    if question.type == "text":
        return [
            PlanSlide(
                id=f"coding-{question.id}",
                kind="coding",
                title=_title(question, "What people said"),
                source=SlideSource(**src, method="autocoder"),
                chart="bar",
                **base,
            )
        ]
    if question.type == "rank":
        return [
            PlanSlide(
                id=f"rank-{question.id}",
                kind="rank_summary",
                title=_title(question, "What matters most"),
                source=SlideSource(**src, statistic="mean_rank"),
                chart="bar",
                **base,
            )
        ]
    if question.type in {"matrix", "grid"}:
        scale = _scale(question)
        if scale == "nps":
            return [
                PlanSlide(
                    id=f"nps-{question.id}",
                    kind="nps",
                    title=_title(question, "Net Promoter Score"),
                    source=SlideSource(**src, statistic="nps"),
                    chart="stacked",
                    **base,
                )
            ]
        if scale == "yes":
            return [
                PlanSlide(
                    id=f"grid-{question.id}",
                    kind="grid_summary",
                    title=_title(question),
                    source=SlideSource(**src, statistic="pct_yes"),
                    chart="bar",
                    **base,
                )
            ]
        return [
            PlanSlide(
                id=f"grid-{question.id}",
                kind="grid_summary",
                title=_title(question, "Top-2 box", prefer="top"),
                source=SlideSource(**src, statistic="top2"),
                chart="bar",
                **base,
            ),
            PlanSlide(
                id=f"mean-{question.id}",
                kind="mean_summary",
                title=_title(question, "Average rating", prefer="mean"),
                source=SlideSource(**src, statistic="mean"),
                chart="bar",
                **base,
            ),
        ]
    return [
        PlanSlide(
            id=f"dist-{question.id}",
            kind="distribution",
            title=_title(question),
            source=SlideSource(**src),
            chart="bar",
            **base,
        )
    ]


def _scale(question: Question) -> str:
    """Classify a grid's answer scale: yes/no, 0-10 recommend, or a rating."""
    labels = [str(o.label) for o in question.options if not is_off_scale_label(str(o.label))]
    codes = [o.code for o in question.options]
    if any(re.fullmatch(r"\s*yes\b.*", label, re.I) for label in labels) and len(labels) <= 3:
        return "yes"
    if len(labels) >= 11 and (0 in codes or "0" in codes):
        return "nps"
    return "rating"


def _funnel(objective: Objective, questions: dict[str, Question]) -> PlanSlide | None:
    """A brand funnel when the objective covers awareness through ownership on yes/no grids."""
    text = objective.text.lower()
    if sum(word in text for word in _FUNNEL_WORDS) < 3:
        return None
    grids = [
        questions[qid]
        for qid in objective.question_ids
        if qid in questions
        and questions[qid].type in {"matrix", "grid"}
        and _scale(questions[qid]) == "yes"
    ]
    if len(grids) < 3:
        return None
    return PlanSlide(
        id=f"funnel-{objective.id.lower()}",
        kind="funnel",
        title="Brand funnel: awareness to ownership",
        purpose="How each brand converts from awareness through consideration and purchase to ownership.",
        objective_ids=[objective.id],
        source=SlideSource(
            question_ids=[q.id for q in grids],
            variables=[v for q in grids for v in variables_of(q)],
            statistic="pct_yes",
        ),
        chart="bar",
    )


def _analysis_slides(questionnaire: Questionnaire, objectives: list[Objective]) -> list[PlanSlide]:
    """Driver analysis and segmentation where the questionnaire supports them."""
    rating = [
        q
        for q in questionnaire.questions
        if q.type in {"matrix", "grid"} and _scale(q) == "rating" and len(variables_of(q)) >= 5
    ]
    outcomes = [
        q
        for q in questionnaire.questions
        if q.type in {"matrix", "grid", "single_select", "rating"} and _OUTCOME.search(q.text)
    ]
    slides: list[PlanSlide] = []
    battery = next((q for q in rating if not _OUTCOME.search(q.text)), None)
    outcome = next((q for q in outcomes if _scale(q) == "nps"), None) or (
        outcomes[0] if outcomes else None
    )
    if battery and outcome:
        target = variables_of(outcome)[0]
        items = variables_of(battery)
        slides.append(
            PlanSlide(
                id=f"drivers-{outcome.id}",
                kind="analysis",
                title="What drives recommendation",
                purpose=f"Which {battery.id} attributes explain {outcome.id}, ranked by importance.",
                objective_ids=_objectives_for(objectives, outcome.id, battery.id),
                source=SlideSource(
                    question_ids=[outcome.id, battery.id],
                    variables=[target, *items],
                    method="key_driver",
                    analysis_request=f"Run a key driver analysis of {target} on {', '.join(items)}.",
                ),
                chart="bar",
            )
        )
    if battery and len(variables_of(battery)) >= 6:
        items = variables_of(battery)
        profile = [
            q.id
            for q in questionnaire.questions
            if q.id.upper().startswith("S") and q.type == "single_select"
        ][:3]
        slides.append(
            PlanSlide(
                id=f"segments-{battery.id}",
                kind="analysis",
                title="Segments in the market",
                purpose=f"Groups of respondents with different {battery.id} attitudes, sized and profiled.",
                objective_ids=_objectives_for(objectives, battery.id),
                source=SlideSource(
                    question_ids=[battery.id],
                    variables=items,
                    method="clustering",
                    analysis_request=(
                        f"Segment respondents on {', '.join(items)}, then profile the segments by "
                        f"{', '.join(profile) or 'the demographics'}."
                    ),
                ),
                chart="bar",
            )
        )
    return slides


def _banner_variables(questionnaire: Questionnaire, support: list[Objective]) -> list[str]:
    names = [qid for o in support for qid in o.question_ids]
    out = []
    for qid in names:
        question = next((q for q in questionnaire.questions if q.id == qid), None)
        if question is None or question.type in {"matrix", "grid", "text"}:
            continue
        out.append(variables_of(question)[0])
    return out[:4]


def _group_slides(
    questionnaire: Questionnaire, banners: list[str], support: list[Objective]
) -> list[PlanSlide]:
    """The headline measure split by each subgroup the objectives ask for."""
    key = next(
        (q for q in questionnaire.questions if q.type in {"matrix", "grid"} and _scale(q) == "nps"),
        None,
    ) or next(
        (q for q in questionnaire.questions if q.type in {"matrix", "grid"} and _scale(q) == "yes"),
        None,
    )
    if key is None or not banners:
        return []
    statistic = "nps" if _scale(key) == "nps" else "pct_yes"
    kind = "nps" if statistic == "nps" else "grid_summary"
    return [
        PlanSlide(
            id=f"group-{key.id}-{banner}",
            kind=kind,
            title=f"{_title(key)} by {banner_label(questionnaire, banner).lower()}",
            purpose=f"Whether {key.id} differs by {banner_label(questionnaire, banner).lower()}.",
            objective_ids=[o.id for o in support],
            source=SlideSource(
                question_ids=[key.id],
                variables=variables_of(key),
                banner=banner,
                statistic=statistic,
            ),
            chart="bar",
        )
        for banner in banners
    ]


def _objectives_for(objectives: list[Objective], *qids: str) -> list[str]:
    return [o.id for o in objectives if any(q in o.question_ids for q in qids)]


def _title(question: Question, fallback: str = "", prefer: str = "") -> str:
    """A slide title from the question's reporting note, else its text.

    With ``prefer``, a note that mentions that word wins (``top`` for a top-2 box
    slide, ``mean`` for a mean slide); with no such note the fallback leads.
    """
    stats = [s for s in question.reporting.stats if s.strip()]
    if prefer:
        stats = [s for s in stats if prefer in s.lower()]
        if not stats:
            return f"{fallback}: {question.text[:70]}"
    if stats:
        title = re.split(r"[:;(]", stats[0])[0].strip()
        return re.sub(r"\s+excluding code \d+", "", title)[:90]
    return fallback or question.text[:90]


def banner_label(questionnaire: Questionnaire, variable: str) -> str:
    """A reader's name for a split variable, such as Gender for S7."""
    for question in questionnaire.questions:
        if variable == question.id or variable in (question.variable_names or []):
            title = _title(question)
            label = re.sub(r"\s+(distribution|quota counts?)$", "", title, flags=re.I)
            return label or variable
    return variable


def _short(text: str) -> str:
    """A section title from an objective: its first clause, without the leading verb."""
    head = re.split(r"[.;:]", text)[0]
    head = re.sub(
        r"^(measure|understand|rank|identify|assess|explore|determine)\s+(the\s+)?",
        "",
        head,
        flags=re.I,
    )
    head = head.strip()
    return (head[:1].upper() + head[1:])[:80] if head else text[:80]
