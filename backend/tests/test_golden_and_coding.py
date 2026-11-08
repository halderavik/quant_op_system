"""Golden fixture crosstab and the open-end coding job."""

import json
from pathlib import Path

import pandas as pd
import pyreadstat
import pytest

from app.engines.coding_agg import merge_checkpoint
from app.engines.crosstab import run_table
from app.engines.spss import read_spss
from app.schemas.coding import Codeframe, CodeNode, CodingAssignment, NetNode
from app.schemas.tabspec import Banner, BannerCategory, StudyDefaults, TableSpec
from app.services.documents import aggregate_saved_coding
from tests.conftest import create_project

ROOT = Path(__file__).resolve().parents[2] / "fixtures"


def test_survey_small_matches_expected_results() -> None:
    """The on-disk fixture matches the hand-written expected_results.json."""
    frame, variables, _weights = read_spss(ROOT / "survey_small.sav")
    banner = Banner(
        id="bn1",
        label="Gender",
        variable_name="gender",
        categories=[
            BannerCategory(label="Male", codes=[1]),
            BannerCategory(label="Female", codes=[2]),
        ],
    )
    spec = TableSpec(
        id="T001",
        title="Trust by gender",
        row_variable_names=["trust"],
        banner_ids=["bn1"],
        weight_variable="weight",
    )
    result = run_table(frame, variables, spec, StudyDefaults(weight_variable="weight"), [banner])
    expected = json.loads((ROOT / "expected_results.json").read_text(encoding="utf-8"))
    total = {row.label: row.cells["total"] for row in result.rows}
    assert total["Low"].unweighted_base == expected["total"]["unweighted_base"]
    assert total["Low"].weighted_base == pytest.approx(expected["total"]["weighted_base"])
    assert total["Low"].estimate == pytest.approx(expected["total"]["low_percent"])
    assert total["High"].estimate == pytest.approx(expected["total"]["high_percent"])
    male = next(row for row in result.rows if row.label == "High").cells["bn1:Male"]
    assert male.unweighted_base == expected["male_high"]["unweighted_base"]
    assert male.weighted_numerator == pytest.approx(expected["male_high"]["weighted_numerator"])
    assert (ROOT / "survey_analysis.sav").exists()
    assert len((ROOT / "oe_labeled.csv").read_text(encoding="utf-8").splitlines()) == 31


def test_open_end_asks_for_a_column_and_a_codeframe(client, tmp_path: Path) -> None:
    """Coding does not invent a dataset, a column, or a codeframe."""
    project = create_project(client)
    response = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": "Please code the open ends"},
    )
    task = client.get(f"/api/tasks/{response.json()['task_id']}").json()
    assert task["status"] == "clarification_needed"
    messages = client.get(f"/api/conversations/{project['conversation_id']}/messages").json()
    assert "dataset" in messages[-1]["content"].lower()
    sav = tmp_path / "tiny.sav"
    pyreadstat.write_sav(pd.DataFrame({"respondent_id": [1], "comment": ["Hello"]}), sav)
    with sav.open("rb") as handle:
        uploaded = client.post(
            f"/api/projects/{project['id']}/files",
            files={"file": ("tiny.sav", handle, "application/octet-stream")},
        )
    assert uploaded.status_code == 201, uploaded.text
    named = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": "code the open-end column comment using respondent id respondent_id"},
    )
    named_task = client.get(f"/api/tasks/{named.json()['task_id']}").json()
    assert named_task["status"] == "clarification_needed"
    messages = client.get(f"/api/conversations/{project['conversation_id']}/messages").json()
    assert "codeframe" in messages[-1]["content"].lower()


def test_open_end_job_codes_text_and_resumes(
    client, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A second run does not call the model again for rows already checkpointed."""
    project = create_project(client)
    frame_path = tmp_path / "oe.sav"
    pyreadstat.write_sav(
        pd.DataFrame(
            {
                "respondent_id": [1, 2, 3],
                "comment": ["Great quality", "Too expensive", ""],
                "weight": [1.0, 1.0, 1.0],
            }
        ),
        frame_path,
    )
    with frame_path.open("rb") as handle:
        uploaded = client.post(
            f"/api/projects/{project['id']}/files",
            files={"file": ("oe.sav", handle, "application/octet-stream")},
        )
    assert uploaded.status_code == 201, uploaded.text
    codeframe = Codeframe(
        codeframe_id="cf",
        response_variable="comment",
        respondent_id_variable="respondent_id",
        codes=[CodeNode(id="C01", label="Quality"), CodeNode(id="C02", label="Price")],
        nets=[NetNode(id="N01", label="Any", child_ids=["C01", "C02"])],
    )
    created = client.post(
        f"/api/projects/{project['id']}/artifacts",
        json={
            "type": "codeframe",
            "name": "Comment codes",
            "content": codeframe.model_dump(mode="json"),
        },
    )
    assert created.status_code == 201, created.text
    calls: list[str] = []

    async def _fake(_settings, frame, prompt, _session_id, existing=None):
        calls.append(prompt)
        rows = []
        for line in prompt.splitlines():
            if "\t" not in line:
                continue
            source, text = line.split("\t", 1)
            if not source.isdigit():
                continue
            code = "C01" if "quality" in text.lower() else "C02"
            rows.append(
                CodingAssignment(
                    respondent_id=source,
                    source_row_id=int(source),
                    response_text=text,
                    assigned_code_ids=[code, "MADE_UP"],
                    sentiment="positive" if code == "C01" else "negative",
                )
            )
        merged = merge_checkpoint(existing or [], rows)
        report, cleaned = aggregate_saved_coding(frame, merged)
        return cleaned, report

    monkeypatch.setattr("app.services.coding_run.code_batch", _fake)
    message = (
        "code the open-end column comment using respondent id respondent_id weight using weight"
    )
    first = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": message},
    )
    task = client.get(f"/api/tasks/{first.json()['task_id']}").json()
    assert task["status"] == "completed", task
    assert len(calls) == 1
    assert "respondent_id" not in calls[0].split("source_row_id\tresponse", 1)[-1]
    assert "Great quality" in calls[0]
    artifacts = client.get(f"/api/projects/{project['id']}/artifacts").json()
    coding = next(item for item in artifacts if item["type"] == "coding")
    assignments = coding["latest"]["content"]["assignments"]
    assert len(assignments) == 3
    coded = next(row for row in assignments if row["response_text"] == "Great quality")
    assert coded["assigned_code_ids"] == ["C01"]
    assert coded["review_required"] is True
    blank = next(row for row in assignments if row["response_text"] == "")
    assert blank["substantive"] is False
    second = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": message},
    )
    again = client.get(f"/api/tasks/{second.json()['task_id']}").json()
    assert again["status"] == "completed"
    assert len(calls) == 1


def test_coding_workbook_matches_the_example_layout() -> None:
    """Punches sit in code columns and the codeframe counts them with COUNTIF."""
    from io import BytesIO

    from openpyxl import load_workbook

    from app.engines.coding_agg import aggregate
    from app.engines.coding_export import export_coding_workbook

    codeframe = Codeframe(
        codeframe_id="cf",
        response_variable="comment",
        respondent_id_variable="record",
        codes=[
            CodeNode(id="C01", label="Quality", value=14),
            CodeNode(id="C02", label="Price", value=51),
        ],
        nets=[NetNode(id="N01", label="POSITIVE (NET)", child_ids=["C01"])],
    )
    assignments = [
        CodingAssignment(
            respondent_id="1",
            source_row_id=0,
            response_text="Great quality",
            assigned_code_ids=["C01", "C02"],
            review_required=True,
            review_reason="Check the second code",
        ),
        CodingAssignment(
            respondent_id="2",
            source_row_id=1,
            response_text="Too expensive",
            assigned_code_ids=["C02"],
        ),
    ]
    report = aggregate(codeframe, assignments)
    workbook = load_workbook(BytesIO(export_coding_workbook(codeframe, assignments, report)))
    assert workbook.sheetnames[:2] == ["Coded_Data", "Codeframe_comment"]
    assert "Review" in workbook.sheetnames
    coded = workbook["Coded_Data"]
    assert [coded.cell(1, column).value for column in range(1, 5)] == [
        "record",
        "comment",
        "comment_Code1",
        "comment_Code2",
    ]
    assert coded["C2"].value == 14
    assert coded["D2"].value == 51
    frame = workbook["Codeframe_comment"]
    assert frame["A5"].value == "Net"
    assert frame["A7"].value == "POSITIVE (NET)"
    assert frame["B8"].value == 14
    assert "COUNTIF(Coded_Data!" in str(frame["D8"].value)
    assert frame["E8"].number_format == "0%"


def test_example_sav_files_use_the_programmed_names() -> None:
    """The sample data files keep the questionnaire variable names."""
    example = Path(__file__).resolve().parents[2] / "example"
    _, small = pyreadstat.read_sav(example / "example_data.sav", metadataonly=True)
    assert "q1_1" in small.column_names
    assert "d1" in small.column_names
    _, brand = pyreadstat.read_sav(example / "one_project" / "221128.sav", metadataonly=True)
    for name in ("S1", "Q1r1", "HVCOHORT"):
        assert name in brand.column_names
