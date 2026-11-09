"""Analyst crosstab plan: workbook style, bases, and within-group tests."""

from io import BytesIO

import pandas as pd
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.engines.crosstab import run_table, run_tabspec
from app.engines.tabspec_build import build_tabspec
from app.engines.tabspec_excel import export_tabspec, import_tabspec
from app.engines.tabspec_text import parse_definition, parse_row_instruction
from app.schemas.expression import Comparison
from app.schemas.questionnaire import Module, Option, Question, Questionnaire
from app.schemas.tabspec import (
    Banner,
    BannerCategory,
    SignificanceSpec,
    StudyDefaults,
    TableSpec,
    TabSpec,
)
from tests.conftest import create_project


def test_analyst_workbook_round_trips_and_parses_a_net() -> None:
    """The five-sheet plan reloads banners, a net, and the table id."""
    spec = TabSpec(
        spec_id="plan",
        dataset_id="sav-1",
        study_defaults=StudyDefaults(study_title="Agent study", sample_size=95),
        banners=[
            Banner(
                id="A_S1",
                label="Role (S1)",
                group="Role (S1)",
                plan="A",
                variable_name="S1",
                variable_note="S1 (as is)",
                categories=[
                    BannerCategory(
                        label="Senior", codes=[1, 2], letter="A", definition="S1 = 1, 2"
                    ),
                    BannerCategory(
                        label="Manager", codes=[3, 4], letter="B", definition="S1 = 3, 4"
                    ),
                ],
            )
        ],
        tables=[
            TableSpec(
                id="T1",
                title="Role",
                section="Screener",
                plan_type="Single",
                stub_label="S1",
                row_variable_names=["S1"],
                banner_plans=["A"],
                banner_ids=["A_S1"],
                row_instruction="All codes; NET Senior (1,2)",
                method="crosstab_sig",
            )
        ],
        exclusions=[{"question_id": "uuid", "reason": "Admin / paradata / ids"}],
    )
    restored = import_tabspec(export_tabspec(spec))
    book = load_workbook(BytesIO(export_tabspec(spec)))
    assert book.sheetnames[:5] == [
        "Overview",
        "Banner specs",
        "Table plan",
        "Derived variables",
        "Not tabbed",
    ]
    assert restored.tables[0].id == "T1"
    assert restored.tables[0].section == "Screener"
    assert restored.tables[0].nets[0].label == "NET Senior"
    assert restored.tables[0].nets[0].child_codes == [1, 2]
    assert restored.banners[0].variable_name == "S1"
    assert restored.banners[0].categories[0].codes == [1, 2]
    assert restored.exclusions[0]["question_id"] == "uuid"
    variable, codes = parse_definition("S1 = 1, 2")
    assert variable == "S1"
    assert codes == [1, 2]
    nets, _, _ = parse_row_instruction("All codes; NET Senior (1,2)")
    assert nets[0].child_codes == [1, 2]


def test_small_base_is_collapsed_and_a_modest_base_is_flagged() -> None:
    """A category under 20 is collapsed. A base of 25 is flagged and kept."""
    frame = pd.DataFrame(
        {
            "S1": [1] * 50 + [2] * 40 + [3] * 5,
            "S2": [1] * 25 + [2] * 70,
            "Q1": [1] * 95,
        }
    )
    variables = [
        {
            "name": "S1",
            "label": "Role",
            "is_text": False,
            "value_labels": {"1": "Senior", "2": "Manager", "3": "Other"},
        },
        {
            "name": "S2",
            "label": "Size",
            "is_text": False,
            "value_labels": {"1": "Small", "2": "Large"},
        },
        {"name": "Q1", "label": "Question", "is_text": False, "value_labels": {"1": "Yes"}},
        {"name": "uuid", "label": "uuid", "is_text": False, "value_labels": {}},
    ]
    spec = build_tabspec(None, variables, frame=frame, dataset_id="d1")
    collapsed = next(banner for banner in spec.banners if banner.source_variable == "S1")
    assert collapsed.variable_name.startswith("BAN_")
    assert any(category.label == "Other collapsed" for category in collapsed.categories)
    assert any(item.kind == "Banner" for item in spec.derived_variables)
    modest = next(banner for banner in spec.banners if banner.source_variable == "S2")
    small = next(category for category in modest.categories if category.label == "Small")
    assert small.n == 25
    assert small.low_base == "*low base"
    assert modest.variable_name == "S2"
    assert any(item["question_id"] == "uuid" for item in spec.exclusions)


def test_unparsed_base_blocks_that_table() -> None:
    """A base sentence that is not a code comparison is not executed."""
    spec = TabSpec(
        spec_id="held",
        banners=[],
        tables=[
            TableSpec(
                id="T9",
                title="Diary",
                row_variable_names=["trust"],
                base_text="Respondents who finished the diary",
                needs_confirmation=True,
                notes=[
                    "Confirm the base before this table runs: Respondents who finished the diary"
                ],
            )
        ],
    )
    frame = pd.DataFrame({"trust": [1, 2]})
    book = run_tabspec(frame, [{"name": "trust", "value_labels": {"1": "Yes"}}], spec)
    assert book.tables == []
    assert book.exceptions[0]["table_id"] == "T9"
    assert "Confirm" in book.exceptions[0]["message"]


def test_significance_letters_stay_inside_one_group() -> None:
    """A large gender gap is lettered. Equal region columns are not compared to it."""
    # Reason: a 0% or 100% column has no variance, so the z-test is undefined.
    # 90% versus 10% is tested. Region is balanced at 50% inside each group.
    rows = [(1, 1)] * 36 + [(2, 1)] * 4 + [(1, 2)] * 4 + [(2, 2)] * 36
    frame = pd.DataFrame(
        {
            "trust": [item[0] for item in rows],
            "gender": [item[1] for item in rows],
            "region": [1 if index % 2 == 0 else 2 for index in range(len(rows))],
        }
    )
    banners = [
        Banner(
            id="gender",
            label="Gender",
            plan="A",
            group="Gender",
            variable_name="gender",
            categories=[
                BannerCategory(label="Male", codes=[1]),
                BannerCategory(label="Female", codes=[2]),
            ],
        ),
        Banner(
            id="region",
            label="Region",
            plan="A",
            group="Region",
            variable_name="region",
            categories=[
                BannerCategory(label="North", codes=[1]),
                BannerCategory(label="South", codes=[2]),
            ],
        ),
    ]
    table = TableSpec(
        id="T1",
        title="Trust",
        row_variable_names=["trust"],
        banner_ids=["gender", "region"],
        banner_plans=["A"],
        significance=SignificanceSpec(enabled=True, minimum_effective_base=10),
    )
    meta = [
        {"name": "trust", "value_labels": {"1": "Low", "2": "High"}, "user_missing_values": []},
        {"name": "gender", "value_labels": {}, "user_missing_values": []},
        {"name": "region", "value_labels": {}, "user_missing_values": []},
    ]
    result = run_table(frame, meta, table, StudyDefaults(), banners)
    low = next(row for row in result.rows if row.label == "Low")
    assert low.cells["gender:Male"].significance_letters == "B"
    assert low.cells["region:North"].significance_letters == ""
    assert low.cells["region:South"].significance_letters == ""


def test_banner_a_and_b_run_as_separate_tables() -> None:
    """A + B produces one result per plan, not one combined test."""
    banners = [
        Banner(
            id="A_gender",
            label="Gender",
            plan="A",
            variable_name="gender",
            categories=[
                BannerCategory(label="Male", codes=[1]),
                BannerCategory(label="Female", codes=[2]),
            ],
        ),
        Banner(
            id="B_region",
            label="Region",
            plan="B",
            variable_name="region",
            categories=[
                BannerCategory(label="North", codes=[1]),
                BannerCategory(label="South", codes=[2]),
            ],
        ),
    ]
    spec = TabSpec(
        spec_id="split",
        banners=banners,
        tables=[
            TableSpec(
                id="T1",
                title="Trust",
                row_variable_names=["trust"],
                banner_plans=["A", "B"],
                banner_ids=["A_gender", "B_region"],
            )
        ],
    )
    frame = pd.DataFrame({"trust": [1, 2], "gender": [1, 2], "region": [1, 2]})
    meta = [
        {"name": "trust", "value_labels": {"1": "Yes", "2": "No"}, "user_missing_values": []},
        {"name": "gender", "value_labels": {}, "user_missing_values": []},
        {"name": "region", "value_labels": {}, "user_missing_values": []},
    ]
    book = run_tabspec(frame, meta, spec)
    assert {table.table_id for table in book.tables} == {"T1-A", "T1-B"}
    banner_a = next(table for table in book.tables if table.table_id == "T1-A")
    assert [column.id for column in banner_a.columns] == [
        "total",
        "A_gender:Male",
        "A_gender:Female",
    ]


def test_builder_uses_sections_bases_grids_and_ranks() -> None:
    """Profile banners, routed bases, grids, ranks, and open ends follow the plan style."""
    document = Questionnaire(
        id="q1",
        title="Agent study",
        modules=[Module(id="m1", title="Screener / profile", question_ids=["S1"])],
        questions=[
            Question(
                id="S1",
                type="screener",
                text="What is your role?",
                variable_names=["S1"],
                options=[Option(code=1, label="Senior"), Option(code=2, label="Manager")],
            ),
            Question(
                id="Q8",
                type="single_select",
                text="How many processes?",
                variable_names=["Q8"],
                options=[Option(code=1, label="None"), Option(code=2, label="Some")],
            ),
            Question(
                id="Q9",
                type="single_select",
                text="What has the organization considered?",
                variable_names=["Q9"],
                display_if=Comparison(op="in", ref="Q8", value=[2, 3, 4, 5]),
                options=[Option(code=1, label="Support")],
            ),
            Question(
                id="Q14",
                type="single_select",
                text="Where are agents deployed?",
                variable_names=["Q14"],
                notes=["Use as a banner"],
                options=[Option(code=1, label="Production")],
            ),
            Question(
                id="Q13",
                type="grid",
                text="How much of a barrier is each?",
                variable_names=["Q13r1", "Q13r2"],
            ),
            Question(
                id="Q32",
                type="rank",
                text="Rank the reasons.",
                variable_names=["Q32r1"],
            ),
            Question(id="Qoe", type="text", text="Why?"),
            Question(
                id="Qrate",
                type="rating",
                text="How clear is the case?",
                variable_names=["Qrate"],
                options=[
                    Option(code=1, label="Low"),
                    Option(code=2, label="Mid low"),
                    Option(code=3, label="Mid high"),
                    Option(code=4, label="High"),
                ],
            ),
        ],
    )
    spec = build_tabspec(document, None)
    by_id = {table.id: table for table in spec.tables}
    role = next(table for table in spec.tables if table.stub_label == "S1")
    assert role.section == "Screener / profile"
    assert role.banner_plans == ["B"]
    routed = next(table for table in spec.tables if table.stub_label == "Q9")
    assert routed.base_text == "Q8 = 2–5"
    assert routed.base.filter is not None
    assert any(table.plan_type == "Grid summary" for table in spec.tables)
    assert sum(table.plan_type == "Grid item" for table in spec.tables) == 2
    assert any(table.plan_type == "Ranking" for table in spec.tables)
    assert any(item.name == "Q32r1_R1" for item in spec.derived_variables)
    assert any(
        table.plan_type == "Open end" and table.row_variable_names == ["Qoe"]
        for table in spec.tables
    )
    assert not any(item["question_id"] == "Qoe" for item in spec.exclusions)
    rated = next(table for table in spec.tables if table.stub_label == "Qrate")
    assert rated.top_box_codes == [3, 4]
    assert rated.bottom_box_codes == [1, 2]
    assert by_id["T1"].id == "T1"


def test_exported_plan_uses_the_example_layout() -> None:
    """Headers, widths, and a 20–29 base match the example workbook."""
    spec = TabSpec(
        spec_id="plan",
        study_defaults=StudyDefaults(study_title="Agent study"),
        banners=[
            Banner(
                id="A_region",
                label="Region",
                plan="A",
                variable_name="region",
                categories=[
                    BannerCategory(label="East", codes=[1], letter="A", n=25),
                    BannerCategory(label="West", codes=[2], letter="B", n=80),
                ],
            )
        ],
        tables=[TableSpec(id="T1", title="Role", row_variable_names=["S1"])],
    )
    book = load_workbook(BytesIO(export_tabspec(spec)))
    header = book["Table plan"]["A1"]
    assert header.font.name == "Arial"
    assert header.font.bold is True
    assert str(header.font.color.rgb).endswith("FFFFFF")
    assert str(header.fill.fgColor.rgb).endswith("1F3864")
    assert book["Banner specs"].column_dimensions["D"].width == 44
    assert book["Table plan"].column_dimensions["D"].width == 52
    assert book["Overview"]["A1"].font.size == 14
    assert str(book["Banner specs"]["A3"].fill.fgColor.rgb).endswith("FCE4D6")
    assert book["Banner specs"]["A4"].fill.patternType is None


def test_user_can_download_the_styled_workbook(client: TestClient) -> None:
    """The download route returns an xlsx named like the analyst plan."""
    project = create_project(client)
    exported = client.post(
        f"/api/projects/{project['id']}/tabspecs/export",
        json={
            "spec_id": "plan",
            "tables": [{"id": "T1", "title": "Role", "row_variable_names": ["S1"]}],
        },
    )
    assert exported.status_code == 200, exported.text
    download = client.get(f"/api/files/{exported.json()['file_id']}/download")
    assert download.status_code == 200
    assert download.headers["content-disposition"].endswith('crosstab-plan.xlsx"')
    book = load_workbook(BytesIO(download.content))
    assert book.sheetnames == [
        "Overview",
        "Banner specs",
        "Table plan",
        "Derived variables",
        "Not tabbed",
    ]
    assert str(book["Table plan"]["A1"].fill.fgColor.rgb).endswith("1F3864")


def test_download_rejects_a_spec_without_a_table_title(client: TestClient) -> None:
    """A table that cannot be validated is not written as a workbook."""
    project = create_project(client)
    exported = client.post(
        f"/api/projects/{project['id']}/tabspecs/export",
        json={"spec_id": "plan", "tables": [{"id": "T1"}]},
    )
    assert exported.status_code == 400
    assert exported.json()["error"]["code"] == "bad_tabspec"
