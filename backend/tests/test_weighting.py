"""Weighting builder: raking, census-target checks, the API flow, and weighted tables."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.agents.orchestrator import _BUILD_WEIGHT, _WEIGHTING_REQUEST
from app.agents.weighting_research import (
    ProposedCategory,
    ProposedDimension,
    ProposedSource,
    TargetProposal,
    collect_urls,
    normalize_url,
)
from app.engines.weighting import (
    achieved_shares,
    efficiency,
    fill_sample_shares,
    rake,
    target_problems,
)
from app.schemas.weighting import TargetCategory, WeightingDimension, WeightingSettings
from app.services import weighting_run
from tests.conftest import create_project

ROOT_SAV = Path(__file__).resolve().parents[2] / "fixtures" / "survey_small.sav"


def _frame() -> pd.DataFrame:
    """200 respondents: 70% men, mostly young, five who would rather not say their gender."""
    rng = np.random.default_rng(7)
    gender = np.array([2] * 135 + [1] * 60 + [99] * 5)
    age = rng.choice([1, 2, 3], size=200, p=[0.5, 0.3, 0.2])
    return pd.DataFrame({"gender": gender, "age": age})


def _dimensions() -> list[WeightingDimension]:
    return [
        WeightingDimension(
            variable="gender",
            categories=[
                TargetCategory(label="Woman", codes=[1], target_share=51),
                TargetCategory(label="Man", codes=[2], target_share=49),
            ],
        ),
        WeightingDimension(
            variable="age",
            categories=[
                TargetCategory(label="18-34", codes=[1], target_share=35),
                TargetCategory(label="35-54", codes=[2], target_share=35),
                TargetCategory(label="55+", codes=[3], target_share=30),
            ],
        ),
    ]


def test_raking_meets_every_target() -> None:
    frame, dims = _frame(), _dimensions()
    weights, facts = rake(frame, dims, WeightingSettings(min_weight=0.1, max_weight=10))
    assert facts["converged"]
    assert weights.mean() == pytest.approx(1.0)
    for row in achieved_shares(frame, dims, weights):
        assert row.weighted_share == pytest.approx(row.target_share, abs=0.05)


def test_no_answer_keeps_its_own_share() -> None:
    """The five 'prefer not to say' respondents still count for 2.5% of the weighted total."""
    frame, dims = _frame(), _dimensions()
    weights, facts = rake(frame, dims, WeightingSettings(min_weight=0.1, max_weight=10))
    share = weights[frame.gender == 99].sum() / weights.sum()
    assert share == pytest.approx(0.025, abs=1e-4)
    assert any("no gender category" in warning for warning in facts["warnings"])


def test_tight_caps_report_missed_targets() -> None:
    frame, dims = _frame(), _dimensions()
    weights, facts = rake(frame, dims, WeightingSettings(min_weight=0.9, max_weight=1.1))
    assert not facts["converged"]
    assert weights.max() <= 1.1 + 1e-6
    assert any("Widen the caps" in warning for warning in facts["warnings"])


def test_target_problems_name_each_fix() -> None:
    frame = _frame()
    dims = _dimensions()
    dims[0].categories[0].target_share = 60
    dims[1].categories[2].target_share = None
    dims[1].categories.append(TargetCategory(label="65+", codes=[4], target_share=5))
    problems = " ".join(target_problems(frame, dims))
    assert "gender targets add up to 109.0%" in problems
    assert "'55+' has no target" in problems
    assert "'65+' has a target of 5% but no respondents" in problems
    assert target_problems(frame, []) == ["Add at least one variable to weight on."]


def test_equal_weights_are_fully_efficient() -> None:
    assert efficiency(pd.Series([1.0] * 10)) == pytest.approx(100.0)
    assert efficiency(pd.Series([0.5, 1.5])) == pytest.approx(80.0)


def test_urls_are_found_anywhere_in_a_block() -> None:
    found: dict[str, str] = {}
    collect_urls(
        {
            "type": "web_search_tool_result",
            "content": [{"url": "https://www.census.gov/a/", "title": "ACS"}],
            "nested": {"citations": [{"url": "https://data.census.gov/t", "title": None}]},
        },
        found,
    )
    assert found == {"https://www.census.gov/a/": "ACS", "https://data.census.gov/t": ""}
    assert normalize_url("https://www.Census.gov/a/#x") == normalize_url("http://census.gov/a")
    assert normalize_url("https://census.gov/a?utm_source=openai") == normalize_url(
        "https://census.gov/a"
    )
    assert normalize_url("https://x.gov/t?id=5&utm_source=openai") == "x.gov/t?id=5"


def test_proposal_is_checked_against_the_search() -> None:
    """Made-up URLs are flagged, unknown codes dropped, and near-100 sums rescaled."""
    frame = pd.DataFrame({"Q17": [1, 2, 1, 2, 99]})
    survey = WeightingDimension(
        variable="Q17",
        categories=[
            TargetCategory(label="Woman", codes=[1]),
            TargetCategory(label="Man", codes=[2]),
        ],
    )
    fill_sample_shares(frame, survey)
    proposal = TargetProposal(
        dimensions=[
            ProposedDimension(
                variable="Q17",
                categories=[
                    ProposedCategory(
                        label="Women", codes=[1], target_share=50.6, source_ids=["S1"]
                    ),
                    ProposedCategory(label="Men", codes=[2], target_share=49.9, source_ids=["S2"]),
                    ProposedCategory(label="Other", codes=[3], target_share=1.0),
                ],
            ),
            ProposedDimension(variable="Q99", categories=[]),
        ],
        sources=[
            ProposedSource(id="S1", title="ACS 2024", url="https://www.census.gov/acs"),
            ProposedSource(id="S2", title="Invented", url="https://example.org/made-up"),
        ],
    )
    dims, sources, notes = weighting_run._merge_proposal(
        proposal, {"https://census.gov/acs/": "ACS"}, {"Q17": survey}, frame
    )
    assert [source.verified for source in sources] == [True, False]
    women, men = dims[0].categories
    assert women.target_share + men.target_share == pytest.approx(100.0, abs=0.02)
    assert "not confirmed" not in women.note
    assert "not confirmed" in men.note
    assert women.origin == "census" and women.sample_share == pytest.approx(40.0)
    assert any("no matching codes" in note for note in notes)
    assert any("Q99" in note for note in notes)


def test_weighting_requests_route_without_the_model() -> None:
    assert _WEIGHTING_REQUEST.search("Propose census targets for weighting")
    assert _WEIGHTING_REQUEST.search("rim weight the data on age and gender")
    assert _WEIGHTING_REQUEST.search("build the weight")
    assert not _WEIGHTING_REQUEST.search("make a weighted crosstab of Q5 by Q17")
    assert _BUILD_WEIGHT.search("build the weight now")
    assert not _BUILD_WEIGHT.search("build weighting targets for US adults")


def _upload(client: TestClient, project_id: str) -> None:
    with ROOT_SAV.open("rb") as handle:
        uploaded = client.post(
            f"/api/projects/{project_id}/files",
            files={"file": ("survey_small.sav", handle, "application/octet-stream")},
        )
    assert uploaded.status_code == 201, uploaded.text


def test_edit_build_and_use_the_weight(client: TestClient) -> None:
    project = create_project(client)
    pid = project["id"]
    _upload(client, pid)
    state = client.get(f"/api/projects/{pid}/weighting").json()
    gender = next(item for item in state["candidates"] if item["variable"] == "gender")
    assert [category["sample_share"] for category in gender["categories"]] == [50.0, 50.0]
    assert state["plan"] is None

    # The user adds their own targets: 40% male, 60% female.
    gender["categories"][0]["target_share"] = 40
    gender["categories"][1]["target_share"] = 60
    plan = {"population": "Test", "dimensions": [gender]}
    saved = client.put(f"/api/projects/{pid}/weighting", json={"plan": plan}).json()
    assert saved["problems"] == []
    built = client.post(f"/api/projects/{pid}/weighting/build")
    assert built.status_code == 200, built.text
    result = built.json()["plan"]["result"]
    assert result["weight_variable"] == "QOS_WEIGHT"
    shares = {row["label"]: row["weighted_share"] for row in result["achieved"]}
    assert shares == {"Male": pytest.approx(40.0), "Female": pytest.approx(60.0)}
    assert result["efficiency"] == pytest.approx(96.2, abs=0.1)

    after = client.get(f"/api/projects/{pid}/weighting").json()
    assert after["project_weight"] == "QOS_WEIGHT" and not after["stale"]
    with client.app.state.session_factory() as db:
        assert weighting_run.project_weight(db, pid, None, "trust by gender") == "QOS_WEIGHT"
        assert weighting_run.project_weight(db, pid, None, "unweighted trust by gender") is None
        assert weighting_run.project_weight(db, pid, "weight", "") == "weight"

    off = client.put(f"/api/projects/{pid}/weighting/use", json={"enabled": False}).json()
    assert off["project_weight"] is None


def test_bad_targets_are_refused(client: TestClient) -> None:
    project = create_project(client)
    pid = project["id"]
    _upload(client, pid)
    dims = [
        {"variable": "gender", "categories": [{"label": "Male", "codes": [1], "target_share": 30}]}
    ]
    saved = client.put(f"/api/projects/{pid}/weighting", json={"plan": {"dimensions": dims}}).json()
    assert "add up to 30.0%" in saved["problems"][0]
    refused = client.post(f"/api/projects/{pid}/weighting/build")
    assert refused.status_code == 400
    assert "not built" in refused.json()["error"]["message"]


def test_propose_saves_researched_targets(client: TestClient, monkeypatch) -> None:
    project = create_project(client)
    pid = project["id"]
    _upload(client, pid)

    async def fake_research(settings, *, population, dimensions, session_id, on_stage=None):
        assert population == "UK adults"
        assert [item["variable"] for item in dimensions] == ["gender"]
        proposal = TargetProposal(
            dimensions=[
                ProposedDimension(
                    variable="gender",
                    categories=[
                        ProposedCategory(
                            label="Male", codes=[1], target_share=49, source_ids=["S1"]
                        ),
                        ProposedCategory(
                            label="Female", codes=[2], target_share=51, source_ids=["S1"]
                        ),
                    ],
                )
            ],
            sources=[ProposedSource(id="S1", title="Census 2021", url="https://www.ons.gov.uk/x")],
        )
        return proposal, {"https://www.ons.gov.uk/x": "Census 2021"}, "notes"

    monkeypatch.setattr(weighting_run, "research_targets", fake_research)
    response = client.post(
        f"/api/projects/{pid}/weighting/propose",
        json={"population": "UK adults", "variables": ["gender"]},
    )
    assert response.status_code == 200, response.text
    plan = response.json()["plan"]
    assert plan["sources"][0]["verified"] is True
    assert [c["target_share"] for c in plan["dimensions"][0]["categories"]] == [49, 51]
    assert plan["status"] == "proposed"
    assert "1 confirmed" in response.json()["summary"]


def test_suggested_variables_are_one_age_gender_and_region() -> None:
    def var(name: str, label: str) -> dict:
        return {"name": name, "label": label, "value_labels": {"1": "a", "2": "b"}}

    found = weighting_run.candidate_variables(
        [
            var("Q6", "Brand image: good value"),
            var("Q21", "Children under age 18 in your home"),
            var("AGE", "Age band"),
            var("Q17", "Gender"),
            var("Q18", "Census region"),
            var("QOS_WEIGHT", "Weight"),
        ]
    )
    suggested = [entry["variable"] for entry in found if entry["suggested"]]
    assert sorted(suggested) == ["AGE", "Q17", "Q18"]
    assert next(entry for entry in found if entry["variable"] == "Q6")["score"] == 0
    assert all(entry["variable"] != "QOS_WEIGHT" for entry in found)


def test_each_variable_is_searched_on_its_own(monkeypatch) -> None:
    """Searches run per variable; one failed search still leaves the others' notes."""
    import asyncio

    from app.agents import weighting_research
    from app.errors import AppError

    asked: list[str] = []

    async def fake_search(settings, request):
        asked.append(request)
        if "- region" in request:
            raise AppError("search failed", "model_error", 502)
        return "figures", {"https://census.gov/t?utm_source=x": "T"}

    async def fake_structured(settings, **kwargs):
        assert "## gender" in kwargs["prompt"] and "## age" in kwargs["prompt"]
        return TargetProposal(dimensions=[], sources=[])

    monkeypatch.setattr(weighting_research, "_search", fake_search)
    monkeypatch.setattr(weighting_research, "run_structured", fake_structured)
    names = ("gender", "age", "region")
    dims = [{"variable": name, "label": name, "categories": []} for name in names]
    _, found, notes = asyncio.run(
        weighting_research.research_targets(
            None, population="US adults", dimensions=dims, session_id="s"
        )
    )
    assert len(asked) == 3 and all(request.count("\n- ") == 1 for request in asked)
    assert "## region" not in notes and list(found) == ["https://census.gov/t?utm_source=x"]


def test_typed_in_age_is_weighted_in_census_bands() -> None:
    from app.engines.weighting import age_bands

    bands = age_bands(pd.Series([18, 30, 41, 52, 64, 65]))
    assert [band.label for band in bands] == ["18–24", "25–34", "35–44", "45–54", "55–65"]
    assert bands[0].codes == list(range(18, 25)) and bands[-1].codes[-1] == 65
    assert age_bands(pd.Series([None, None])) == []
    assert age_bands(pd.Series([19, 40]))[0].label == "18–24"


def test_brand_grids_and_live_questions_are_read_correctly() -> None:
    """'statement' is not a state; 'where do you live' is a region; a typed age counts."""
    labelled = {"1": "a", "2": "b", "3": "c"}
    found = weighting_run.candidate_variables(
        [
            {
                "name": "Q10r4",
                "label": "Reliable: how well does each statement describe the brand?",
                "value_labels": labelled,
            },
            {"name": "S1", "label": "What is your age?", "value_labels": {}},
            {"name": "S5", "label": "Where do you currently live?", "value_labels": labelled},
            {"name": "S6", "label": "How do you describe your gender?", "value_labels": labelled},
        ]
    )
    concepts = {entry["variable"]: (entry["concept"], entry["suggested"]) for entry in found}
    assert concepts["Q10r4"] == ("", False)
    assert concepts["S1"] == ("age", True)
    assert concepts["S5"] == ("region", True)
    assert concepts["S6"] == ("gender", True)
