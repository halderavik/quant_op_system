"""Tracking studies: next wave, wave changes, and trend tables."""

from pathlib import Path

import numpy as np
import pandas as pd
import pyreadstat
from fastapi.testclient import TestClient

from app.schemas.expression import Comparison
from app.schemas.questionnaire import Option, ProgrammingSpec, Question, Questionnaire
from app.services.tracking import compare_waves
from tests.conftest import create_project


def _questionnaire() -> Questionnaire:
    return Questionnaire(
        id="t",
        title="Brand Tracker",
        questions=[
            Question(
                id="Q1",
                type="single_select",
                text="Which brand do you buy most often?",
                options=[Option(code=1, label="Alpha"), Option(code=2, label="Beta")],
                programming=ProgrammingSpec(min_value=None),
            ),
            Question(
                id="Q2",
                type="numeric",
                text="How many times a month?",
                display_if=Comparison(op="eq", ref="Q1", value=1),
            ),
            Question(id="Q3", type="text", text="Why?"),
        ],
    )


def _upload(client: TestClient, project_id: str, path: Path, frame: pd.DataFrame) -> None:
    pyreadstat.write_sav(frame, path, variable_value_labels={"Q1": {1: "Alpha", 2: "Beta"}})
    with path.open("rb") as handle:
        response = client.post(
            f"/api/projects/{project_id}/files",
            files={"file": (path.name, handle, "application/octet-stream")},
        )
    assert response.status_code == 201, response.text


def _wave(share_alpha: float, mean: float, n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    q1 = np.where(rng.random(n) < share_alpha, 1.0, 2.0)
    return pd.DataFrame({"Q1": q1, "Q2": rng.normal(mean, 1.0, n).round(1)})


def test_next_wave_copies_materials_and_links_the_series(client: TestClient) -> None:
    project = create_project(client, "Tracker W1")
    saved = client.post(
        f"/api/projects/{project['id']}/questionnaires",
        json=_questionnaire().model_dump(mode="json"),
    )
    assert saved.status_code == 200, saved.text
    assert client.get(f"/api/projects/{project['id']}/tracking").json() == {
        "tracking": {},
        "waves": [],
    }
    created = client.post(
        f"/api/projects/{project['id']}/tracking/next-wave",
        json={"name": "Tracker W2", "label": "Q2 2026"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["wave"] == 2 and body["copied"] == ["questionnaire"]
    waves = client.get(f"/api/projects/{body['project_id']}/tracking").json()["waves"]
    assert [(w["wave"], w["label"], w["current"]) for w in waves] == [
        (1, "Wave 1", False),
        (2, "Q2 2026", True),
    ]
    artifacts = client.get(f"/api/projects/{body['project_id']}/artifacts").json()
    copied = next(a for a in artifacts if a["type"] == "questionnaire")
    assert copied["latest"]["content"]["title"] == "Brand Tracker"
    # Nothing changed yet between the waves.
    changes = client.get(f"/api/projects/{body['project_id']}/tracking/changes").json()
    assert changes["changes"] == [] and changes["unchanged"] == 3
    # Wave 3 continues the numbering from wave 2.
    third = client.post(f"/api/projects/{body['project_id']}/tracking/next-wave", json={}).json()
    assert third["wave"] == 3 and third["label"] == "Wave 3"


def test_wave_changes_flag_what_breaks_the_trend() -> None:
    before = _questionnaire()
    now = _questionnaire()
    now.questions[0] = now.questions[0].model_copy(
        update={
            "options": [
                Option(code=1, label="Alpha"),
                Option(code=2, label="Beta Brand"),
                Option(code=3, label="Gamma"),
            ]
        }
    )
    now.questions[1] = now.questions[1].model_copy(update={"display_if": None})
    now.questions = [
        now.questions[0],
        now.questions[1],
        Question(id="Q4", type="text", text="New"),
    ]
    result = compare_waves(before, now)
    by_id = {row["question_id"]: row for row in result["changes"]}
    assert by_id["Q1"]["breaks_trend"] and any("3 Gamma" in n for n in by_id["Q1"]["notes"])
    assert any("Beta" in n and "Beta Brand" in n for n in by_id["Q1"]["notes"])
    assert by_id["Q2"]["notes"] == ["Base (who is asked) changed."]
    assert by_id["Q3"]["status"] == "removed" and by_id["Q4"]["status"] == "added"
    assert result["breaks_trend"] == 3 and result["added"] == 1


def test_trend_table_tests_each_wave_against_the_previous(
    client: TestClient, tmp_path: Path
) -> None:
    first = create_project(client, "Tracker W1")
    _upload(client, first["id"], tmp_path / "w1.sav", _wave(0.40, 5.0, 600, 1))
    second = client.post(
        f"/api/projects/{first['id']}/tracking/next-wave", json={"label": "Wave 2"}
    ).json()
    _upload(client, second["project_id"], tmp_path / "w2.sav", _wave(0.55, 5.02, 600, 2))

    names = [
        v["name"] for v in client.get(f"/api/projects/{first['id']}/tracking/variables").json()
    ]
    assert {"Q1", "Q2"} <= set(names)
    response = client.post(
        f"/api/projects/{second['project_id']}/tracking/trend", json={"variables": ["Q1", "Q2"]}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [w["label"] for w in body["waves"]] == ["Wave 1", "Wave 2"]
    q1, q2 = body["tables"]
    alpha = next(row for row in q1["rows"] if row["label"] == "Alpha")
    assert alpha["cells"][0]["change"] is None
    assert alpha["cells"][1]["significant"] and alpha["cells"][1]["direction"] == "up"
    assert q2["kind"] == "numeric"
    mean = q2["rows"][0]
    assert mean["label"] == "Mean" and not mean["cells"][1]["significant"]


def test_trend_needs_two_waves_with_data(client: TestClient, tmp_path: Path) -> None:
    first = create_project(client, "Solo")
    _upload(client, first["id"], tmp_path / "w1.sav", _wave(0.4, 5.0, 50, 1))
    client.post(f"/api/projects/{first['id']}/tracking/next-wave", json={})
    response = client.post(
        f"/api/projects/{first['id']}/tracking/trend", json={"variables": ["Q1"]}
    )
    assert response.status_code == 400
