"""Report planner: draft, coverage, merge, data stage, and the generated PPTX."""

from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
import pyreadstat
from pptx import Presentation

from app.agents.report_planner import NewAnalysis, PlanRefinement, apply_refinement
from app.agents.report_writer import allowed_numbers, fallback_text, numbers_ok
from app.engines.report.plan_rules import draft_plan, merge
from app.schemas.questionnaire import Questionnaire
from tests.conftest import create_project

BRANDS = ["BrewCo", "Kaffina", "MorningPress"]
ATTRS = ["Good value", "Great taste", "Reliable", "Easy to clean", "Modern design", "Trusted brand"]


def _grid(qid: str, text: str, stat: str, options: list[dict], items: list[str]) -> dict:
    return {
        "id": qid,
        "type": "matrix",
        "text": text,
        "options": options,
        "matrix_items": items,
        "variable_names": [f"{qid}r{i + 1}" for i in range(len(items))],
        "reporting": {"stats": [stat]},
    }


YES = [{"code": 1, "label": "Yes"}, {"code": 2, "label": "No"}]
RATE = [{"code": c, "label": f"Point {c}"} for c in range(1, 6)] + [
    {"code": 97, "label": "Don't know"}
]
NPS = [{"code": c, "label": str(c)} for c in range(11)]
QUESTIONNAIRE = {
    "id": "qn",
    "title": "Coffee Brand Health",
    "objectives": [
        {
            "id": "O1",
            "description": "Measure awareness, consideration, purchase and ownership by brand.",
            "question_ids": ["Q2", "Q3", "Q4", "Q5"],
        },
        {
            "id": "O2",
            "description": "Measure brand image on six attributes.",
            "question_ids": ["Q7"],
        },
        {
            "id": "O3",
            "description": "Measure likelihood to recommend and reasons.",
            "question_ids": ["Q14", "Q15"],
        },
        {"id": "O4", "description": "Support analysis by gender.", "question_ids": ["S7"]},
    ],
    "questions": [
        {"id": "S1", "type": "screener", "text": "Do you live in the US?", "options": YES},
        {
            "id": "S7",
            "type": "single_select",
            "text": "How do you describe your gender?",
            "options": [{"code": 1, "label": "Woman"}, {"code": 2, "label": "Man"}],
            "reporting": {"stats": ["Gender distribution"]},
        },
        _grid("Q2", "Have you heard of each brand?", "Aided awareness by brand", YES, BRANDS),
        _grid("Q3", "Would you consider each brand?", "Consideration by brand", YES, BRANDS),
        _grid(
            "Q4",
            "Have you bought each brand in the past 12 months?",
            "Purchase by brand",
            YES,
            BRANDS,
        ),
        _grid("Q5", "Do you own each brand?", "Ownership by brand", YES, BRANDS),
        _grid(
            "Q7",
            "How well does each statement describe BrewCo?",
            "Top-two-box attribute ratings",
            RATE,
            ATTRS,
        ),
        {
            "id": "Q12",
            "type": "single_select",
            "text": "For this question only, please select Somewhat disagree.",
            "options": RATE[:5],
        },
        _grid("Q14", "How likely are you to recommend each brand?", "NPS by brand", NPS, BRANDS),
        {
            "id": "Q15",
            "type": "text",
            "text": "Why did you give that score?",
            "reporting": {"stats": ["Coded reasons"]},
        },
    ],
}


def _questionnaire() -> Questionnaire:
    return Questionnaire.model_validate(QUESTIONNAIRE)


def test_draft_places_every_reportable_question_in_story_order() -> None:
    plan = draft_plan(_questionnaire())
    ids = [section.id for section in plan.sections]
    assert ids[:2] == ["sec-intro", "sec-sample"]
    assert ids[-2:] == ["sec-close", "sec-appendix"]
    kinds = {slide.id: slide.kind for slide in plan.all_slides()}
    assert kinds["funnel-o1"] == "funnel"
    assert kinds["grid-Q7"] == "grid_summary" and kinds["mean-Q7"] == "mean_summary"
    assert kinds["nps-Q14"] == "nps" and kinds["coding-Q15"] == "coding"
    assert kinds["drivers-Q14"] == "analysis" and kinds["segments-Q7"] == "analysis"
    assert kinds["group-Q14-S7"] == "nps"
    reasons = {row.question_id: row.reason for row in plan.coverage if not row.slide_ids}
    assert set(reasons) == {"S1", "Q12"}
    assert "Attention check" in reasons["Q12"]


def test_merge_keeps_user_edits_additions_and_removals() -> None:
    old = draft_plan(_questionnaire())
    section = next(s for s in old.sections if s.id == "sec-o2")
    section.slides[0] = section.slides[0].model_copy(
        update={"title": "My own title", "edited": True}
    )
    section.slides.append(
        section.slides[0].model_copy(update={"id": "user-x", "origin": "user", "title": "Added"})
    )
    old.removed_slide_ids = ["mean-Q7"]
    new = merge(draft_plan(_questionnaire()), old)
    slides = {s.id: s for s in new.all_slides()}
    assert slides["grid-Q7"].title == "My own title"
    assert slides["user-x"].title == "Added"
    assert slides["mean-Q7"].status == "dropped"


def test_planner_agent_additions_must_name_real_variables() -> None:
    plan = draft_plan(_questionnaire())
    refined, notes = apply_refinement(
        plan,
        PlanRefinement(
            add=[
                NewAnalysis(
                    section_id="sec-o2",
                    title="Brand image map",
                    purpose="x",
                    method="correspondence",
                    variables=["Q7r1", "Q7r2"],
                    analysis_request="Run a correspondence analysis.",
                ),
                NewAnalysis(
                    section_id="sec-o2",
                    title="Bad",
                    purpose="x",
                    method="correspondence",
                    variables=["NOPE"],
                    analysis_request="x",
                ),
            ]
        ),
        _questionnaire(),
    )
    titles = [s.title for s in refined.all_slides()]
    assert "Brand image map" in titles and "Bad" not in titles
    assert len(notes) == 1


def test_headlines_may_only_quote_computed_numbers() -> None:
    facts = [
        {"label": "BrewCo", "value": 73.0, "unit": "%"},
        {"label": "Kaffina", "value": 66.0, "unit": "%"},
    ]
    allowed = allowed_numbers(facts)
    assert numbers_ok("BrewCo leads at 73%, 7 points ahead of Kaffina", allowed)
    assert not numbers_ok("BrewCo leads at 81%", allowed)
    assert (
        "73"
        in fallback_text({"title": "Awareness", "kind": "grid_summary", "facts": facts})["headline"]
    )


def test_numbers_inside_labels_and_ranges_are_not_invented() -> None:
    facts = [
        {"label": "BrewCo NPS ($75,000–$99,999)", "value": -13, "unit": ""},
        {"label": "BrewCo NPS (18-34)", "value": -40, "unit": ""},
    ]
    allowed = allowed_numbers(facts)
    assert numbers_ok("Among $75,000–$99,999 households BrewCo NPS is -13", allowed)
    assert numbers_ok("18-34s give BrewCo its weakest NPS, at -40", allowed)
    assert not numbers_ok("BrewCo NPS is -25 among 18-34s", allowed)
    headline = fallback_text({"title": "NPS by income", "kind": "nps", "facts": facts})["headline"]
    assert headline.startswith("NPS ranges from -13 (BrewCo among $75,000–$99,999)")


def test_report_analyses_run_without_asking_questions() -> None:
    from app.schemas.report_plan import PlanSlide, SlideSource
    from app.services.report_run import unattended_request

    slide = PlanSlide(
        id="ai-x",
        kind="analysis",
        title="Group differences",
        purpose="x",
        source=SlideSource(
            variables=["Q3r1", "S2"], method="chi_square", analysis_request="Compare by age."
        ),
    )
    text = unattended_request(slide)
    assert "Q3r1, S2" in text and "Do not ask for clarification" in text and "18-34" in text
    grid = slide.model_copy(
        update={"source": slide.source.model_copy(update={"variables": ["Q7r1", "Q7r2", "S2"]})}
    )
    assert "custom procedure" in unattended_request(grid)
    assert "custom procedure" not in text


def _data(path: Path, n: int = 240) -> None:
    rng = np.random.default_rng(5)
    affinity = rng.normal(size=n)
    data: dict[str, np.ndarray] = {
        "respondent_id": np.arange(1, n + 1).astype(float),
        "S7": rng.integers(1, 3, n).astype(float),
    }
    labels: dict[str, str] = {"S7": "S7: How do you describe your gender?"}
    values: dict[str, dict] = {"S7": {1: "Woman", 2: "Man"}}
    for q, cut in (("Q2", 0.6), ("Q3", 0.2), ("Q4", -0.4), ("Q5", -0.7)):
        for i, brand in enumerate(BRANDS):
            name = f"{q}r{i + 1}"
            data[name] = np.where(
                affinity - 0.3 * i + rng.normal(scale=0.5, size=n) > -cut, 1.0, 2.0
            )
            labels[name] = f"{q} {brand}: question"
            values[name] = {1: "Yes", 2: "No"}
    for i, attr in enumerate(ATTRS):
        name = f"Q7r{i + 1}"
        col = np.clip(np.round(3 + affinity + rng.normal(scale=0.8, size=n)), 1, 5)
        col[rng.choice(n, 10, replace=False)] = 97
        data[name] = col
        labels[name] = f"Q7 {attr}: How well does each statement describe BrewCo?"
        values[name] = {**{c: f"Point {c}" for c in range(1, 6)}, 97: "Don't know"}
    for i, brand in enumerate(BRANDS):
        name = f"Q14r{i + 1}"
        data[name] = np.clip(np.round(6 + 2 * affinity - i + rng.normal(size=n)), 0, 10)
        labels[name] = f"Q14 {brand}: How likely are you to recommend each brand?"
    data["Q15"] = np.array(
        ["Great taste every morning" if a > 0 else "Too expensive for me" for a in affinity],
        dtype=object,
    )
    labels["Q15"] = "Q15: Why did you give that score?"
    frame = pd.DataFrame(data)
    pyreadstat.write_sav(frame, path, column_labels=labels, variable_value_labels=values)


def _ask(client, project: dict, text: str) -> dict:
    sent = client.post(
        f"/api/conversations/{project['conversation_id']}/messages", json={"content": text}
    )
    return client.get(f"/api/tasks/{sent.json()['task_id']}").json()


def _latest(client, project: dict, kind: str) -> dict:
    artifacts = client.get(f"/api/projects/{project['id']}/artifacts").json()
    return next(item for item in artifacts if item["type"] == kind)


def test_plan_then_data_then_editable_pptx(client, tmp_path: Path) -> None:
    project = create_project(client)
    created = client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={"type": "questionnaire", "name": "Coffee", "content": QUESTIONNAIRE},
    )
    assert created.status_code == 201, created.text
    task = _ask(client, project, "Show me the report plan")
    assert task["status"] == "completed", task
    plan = _latest(client, project, "report_plan")["latest"]["content"]
    assert plan["stage"] == "draft"
    path = tmp_path / "coffee.sav"
    _data(path)
    with path.open("rb") as handle:
        uploaded = client.post(
            f"/api/projects/{project['id']}/files",
            files={"file": ("coffee.sav", handle, "application/octet-stream")},
        )
    assert uploaded.status_code == 201, uploaded.text
    plan = _latest(client, project, "report_plan")["latest"]["content"]
    assert plan["stage"] == "data_ready"
    assert plan["data"]["raw_n"] == 240 and plan["data"]["final_n"] is not None
    funnel = next(s for sec in plan["sections"] for s in sec["slides"] if s["id"] == "funnel-o1")
    assert funnel["base_n"] == plan["data"]["final_n"]
    task = _ask(client, project, "Generate the report")
    assert task["status"] in {"completed", "completed_with_warnings"}, task
    report = _latest(client, project, "report")["latest"]["content"]
    deck = client.get(f"/api/files/{report['export_file_id']}/download")
    assert deck.status_code == 200
    prs = Presentation(BytesIO(deck.content))
    charts = [shape for slide in prs.slides for shape in slide.shapes if shape.has_chart]
    assert len(charts) >= 6
    titles = [s["title"] for s in report["slides"]]
    assert titles[0] == "Coffee Brand Health"
    assert "Key takeaways" in titles
    assert titles.index("What this study set out to answer") < titles.index("Key takeaways")
    plan = _latest(client, project, "report_plan")["latest"]["content"]
    assert plan["stage"] == "reported"


def test_grid_rows_named_differently_in_the_data_are_matched() -> None:
    from app.engines.report.data_fit import data_name, fit_data

    columns = ["Q10r1", "Q10r2", "Q10r10", "Q3r98oe", "S6"]
    assert data_name("Q10a1", columns) == "Q10r1"
    assert data_name("Q10a10", columns) == "Q10r10"
    assert data_name("Q3a98", columns) == "Q3a98"
    plan = draft_plan(_questionnaire())
    renamed = {f"Q7r{i}": f"Q7x{i}" for i in range(1, 7)}
    rng = np.random.default_rng(1)
    frame = pd.DataFrame({name: rng.integers(1, 6, 240).astype(float) for name in renamed.values()})
    fitted = fit_data(plan, frame, [])
    grid = next(s for s in fitted.all_slides() if s.id == "grid-Q7")
    assert grid.source.variables == list(renamed.values())
    assert grid.status == "planned" and grid.base_n == 240


def test_cleaning_choice_from_chat() -> None:
    from app.agents.orchestrator import cleaning_choice

    assert cleaning_choice("Skip the data cleaning") == "skip"
    assert cleaning_choice("Update the report plan without cleaning the data") == "skip"
    assert cleaning_choice("Clean the data for the report anyway") == "run"
    assert cleaning_choice("Update the report plan with the data") is None


def test_synthetic_data_skips_cleaning_unless_asked(client, tmp_path: Path) -> None:
    project = create_project(client)
    client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={"type": "questionnaire", "name": "Coffee", "content": QUESTIONNAIRE},
    )
    _ask(client, project, "Show me the report plan")
    path = tmp_path / "synthetic-data.sav"
    _data(path)
    with path.open("rb") as handle:
        client.post(
            f"/api/projects/{project['id']}/files",
            files={"file": ("synthetic-data.sav", handle, "application/octet-stream")},
        )
    plan = _latest(client, project, "report_plan")["latest"]["content"]
    assert plan["data"]["synthetic"] is True
    assert plan["data"]["removed_by_cleaning"] == 0
    assert "skipped" in plan["data"]["cleaning_summary"]
    assert not any(
        a["type"] == "cleaning"
        for a in client.get(f"/api/projects/{project['id']}/artifacts").json()
    )
    task = _ask(client, project, "Update the report plan and clean the data anyway")
    assert task["status"] in {"completed", "completed_with_warnings"}, task
    plan = _latest(client, project, "report_plan")["latest"]["content"]
    assert plan["cleaning"] == "run"
    assert "skipped" not in plan["data"]["cleaning_summary"]
