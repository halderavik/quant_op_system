"""Charts are produced for analyses, AI-written methods, crosstabs, and coding."""

from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook

from app.engines.analysis.plots import clean_specs
from app.engines.analysis.report import build_report
from app.engines.analysis.workbook import workbook_bytes
from app.engines.analysis.workflow import execute_workflow
from app.engines.chart_render import render
from app.schemas.analysis import AnalysisResult, AnalysisStep
from tests.test_autocode import settings  # noqa: F401  (OpenAI key set; the model is faked)
from tests.test_multistep_analysis import _frame, _variables, _workflow

PNG = b"\x89PNG"


def _charts(*steps: AnalysisStep) -> tuple[dict, list[str]]:
    result = execute_workflow(_frame(), _workflow(*steps), _variables())
    return result, [spec["title"] for spec in result["charts"]]


def test_each_method_gets_its_standard_charts() -> None:
    _, titles = _charts(
        AnalysisStep(
            step_id="s1",
            kind="method",
            method="key_driver",
            dependent="nps",
            predictors=["img2", "img5"],
            reason="x",
        )
    )
    assert titles == ["Driver importance"]
    _, titles = _charts(
        AnalysisStep(
            step_id="s1", kind="method", method="clustering", variables=["img2", "img3"], reason="x"
        ),
        AnalysisStep(step_id="p", kind="profile_crosstab", variables=["gender"], reason="x"),
    )
    assert {"Segment count search", "Segment sizes", "Segment feature means"} <= set(titles)
    assert any(title.startswith("Profile: gender") for title in titles)
    _, titles = _charts(
        AnalysisStep(
            step_id="s1", kind="method", method="anova", dependent="nps", group="region", reason="x"
        ),
        AnalysisStep(
            step_id="s2",
            kind="method",
            method="chi_square",
            var_a="gender",
            var_b="region",
            reason="x",
        ),
        AnalysisStep(
            step_id="s3",
            kind="method",
            method="efa",
            k=2,
            variables=["img2", "img3", "img5", "img6"],
            reason="x",
        ),
    )
    assert "Mean nps by region" in titles
    assert "region within gender (row %)" in titles
    assert {"Variance explained by factor", "Rotated loadings"} <= set(titles)


def test_split_runs_get_one_chart_per_group_and_a_comparison() -> None:
    _, titles = _charts(
        AnalysisStep(
            step_id="s1",
            kind="method",
            method="key_driver",
            dependent="nps",
            predictors=["img2", "img5"],
            split_by="gender",
            reason="x",
        )
    )
    assert "Driver importance — Male" in titles and "Driver importance — Female" in titles
    assert "Driver importance by gender" in titles


def test_specs_render_and_land_in_the_workbook(tmp_path: Path) -> None:
    result, _ = _charts(
        AnalysisStep(
            step_id="s1",
            kind="method",
            method="correlation",
            variables=["img2", "img3", "nps"],
            reason="x",
        )
    )
    path = render(result["charts"][0], tmp_path / "c.png")
    image = path.read_bytes()
    assert image.startswith(PNG)
    plan = _workflow(
        AnalysisStep(
            step_id="s1", kind="method", method="correlation", variables=["img2"], reason="x"
        )
    )
    report = build_report("t", AnalysisResult.model_validate(result))
    book = load_workbook(BytesIO(workbook_bytes(plan, result, report, [("Correlation", image)])))
    assert "Charts" in book.sheetnames
    assert book["Charts"]._images


def test_script_charts_are_checked_before_drawing(tmp_path: Path) -> None:
    good = {
        "kind": "line",
        "title": "Price sensitivity",
        "series": [{"name": "Too cheap", "x": [50, 100, 150], "y": [0.9, 0.3, 0.05]}],
        "markers": [{"x": 103, "label": "OPP"}],
    }
    kept, notes = clean_specs(
        [good, {"kind": "pie", "title": "x"}, {"kind": "bar", "title": "x", "series": []}, "junk"]
    )
    assert [spec["title"] for spec in kept] == ["Price sensitivity"]
    assert len(notes) == 3
    assert render(kept[0], tmp_path / "p.png").read_bytes().startswith(PNG)


def test_a_crosstab_and_a_coding_run_store_charts(client, monkeypatch, tmp_path: Path) -> None:
    from tests.conftest import create_project
    from tests.test_autocode import _FakeLLM, _upload

    monkeypatch.setattr("app.services.autocode_run._llm_factory", lambda _settings: _FakeLLM)
    monkeypatch.setattr("app.services.autocode_run.autocoder_available", lambda: True)
    project = create_project(client)
    _upload(client, project, tmp_path)
    for text in ("S7 by S7", "Auto-code the open ends in Q15"):
        sent = client.post(
            f"/api/conversations/{project['conversation_id']}/messages", json={"content": text}
        )
        client.get(f"/api/tasks/{sent.json()['task_id']}")
    artifacts = client.get(f"/api/projects/{project['id']}/artifacts").json()
    kinds = {item["type"]: item["latest"]["content"] for item in artifacts}
    assert kinds["crosstab"]["chart_file_id"]
    coding = kinds["coding"]
    assert [chart["title"] for chart in coding["charts"]] == ["Q15: nets", "Q15: top codes"]
    image = client.get(f"/api/files/{coding['chart_file_id']}/download")
    assert image.status_code == 200 and image.content.startswith(PNG)
