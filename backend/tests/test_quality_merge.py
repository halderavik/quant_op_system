"""Live quality flags joined to uploaded survey data as LQ_ variables."""

from pathlib import Path

import numpy as np
import pandas as pd
import pyreadstat
import pytest
from fastapi.testclient import TestClient

from app.errors import AppError
from app.services import live_quality, quality_merge
from tests.conftest import create_project

DETAILED = {
    "respondents": [
        {
            "session_id": "s-bot",
            "respondent_id": "R-1",
            "created_at": "2026-11-16T10:00:00+00:00",
            "is_bot": True,
            "confidence_score": 0.92,
            "risk_level": "HIGH",
            "fraud_score": 0.4,
            "flagged_patterns": {"base_score": 0.92, "decisive_codes": ["honeypot"]},
        },
        {
            "session_id": "s-fraud",
            "respondent_id": "R-2",
            "created_at": "2026-11-16T10:05:00+00:00",
            "confidence_score": 0.2,
            "risk_level": "LOW",
            "fraud_score": 0.85,
            "is_duplicate": True,
        },
        {
            "session_id": "s-human",
            "respondent_id": "R-3",
            "created_at": "2026-11-16T10:07:00+00:00",
            "confidence_score": 0.1,
            "risk_level": "LOW",
            "fraud_score": 0.05,
        },
    ]
}


def _result() -> dict:
    return live_quality.summarize("BrewCo", {}, DETAILED)


def test_records_get_flags_matched_by_session_then_respondent() -> None:
    """Each record gets its own row's flags; untracked or unknown records are marked unmatched."""
    frame = pd.DataFrame(
        {
            "record": [1, 2, 3, 4, 5],
            "QOS_SESSION": ["s-bot", "", "s-human", "s-missing", ""],
            "QOS_RESPONDENT": ["", "R-2", "", "", ""],
        }
    )
    merged, variables, report = quality_merge.add_quality_columns(frame, [{"name": "record"}], _result())
    assert list(merged["LQ_MATCHED"]) == [1, 1, 1, 0, 0]
    assert list(merged["LQ_VERDICT"][:3]) == [2, 1, 1]
    assert list(merged["LQ_F_BOT"][:3]) == [1, 0, 0]
    assert list(merged["LQ_F_FRAUD"][:3]) == [0, 1, 0]
    assert list(merged["LQ_F_DUPLICATE"][:3]) == [0, 1, 0]
    assert merged.loc[0, "LQ_BOT_SIGNALS"] == "Hidden honeypot field filled in"
    assert merged.loc[1, "LQ_FRAUD_RISK"] == 3 and merged.loc[2, "LQ_FRAUD_RISK"] == 1
    assert np.isnan(merged.loc[3, "LQ_BOT_SCORE"]) and merged.loc[3, "LQ_FLAGS"] == ""
    assert report["tracked"] == 4 and report["matched"] == 3 and report["unmatched"] == 1
    assert report["bots"] == 1 and report["flagged"] == 2
    labels = {item["name"]: item for item in variables}
    assert labels["LQ_F_BOT"]["value_labels"] == {"0": "No", "1": "Yes"}
    assert labels["LQ_FLAGS"]["is_text"] is True

    # Running it again replaces the LQ_ columns rather than adding a second set.
    again, again_variables, _ = quality_merge.add_quality_columns(merged, variables, _result())
    assert list(again.columns) == list(merged.columns)
    assert len(again_variables) == len(variables)


def _upload(client: TestClient, project_id: str, path: Path, frame: pd.DataFrame) -> dict:
    pyreadstat.write_sav(frame, path)
    with path.open("rb") as handle:
        response = client.post(
            f"/api/projects/{project_id}/files",
            files={"file": (path.name, handle, "application/octet-stream")},
        )
    assert response.status_code == 201, response.text
    return response.json()


def test_upload_adds_flags_and_refresh_makes_a_new_version(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tracked Decipher export gets LQ_ variables on upload; a refresh saves version 2."""
    calls: list[str] = []

    async def _fake(settings, survey_id, rules=None):
        calls.append(survey_id)
        return _result()

    monkeypatch.setattr(live_quality, "live_results", _fake)
    project = create_project(client, "BrewCo")
    body = _upload(
        client, project["id"], tmp_path / "decipher.sav",
        pd.DataFrame({"Q1": [1.0, 2.0, 1.0], "QOS_SESSION": ["s-bot", "s-fraud", "s-human"]}),
    )
    assert body["live_quality"]["status"] == "merged"
    assert body["live_quality"]["matched"] == 3
    dataset = client.get(f"/api/datasets/{body['dataset_id']}").json()
    names = [item["name"] for item in dataset["variables"]]
    assert "LQ_F_BOT" in names and "LQ_FLAGS" in names and names[:2] == ["Q1", "QOS_SESSION"]

    state = client.get(f"/api/projects/{project['id']}/live-quality").json()
    assert state["data"]["tracked"] and state["data"]["merged"]
    assert state["data"]["last"]["matched"] == 3

    refreshed = client.post(f"/api/projects/{project['id']}/live-quality/merge")
    assert refreshed.status_code == 200, refreshed.text
    new_id = refreshed.json()["report"]["dataset_id"]
    assert new_id != body["dataset_id"]
    names = [item["name"] for item in client.get(f"/api/datasets/{new_id}").json()["variables"]]
    assert names.count("LQ_F_BOT") == 1
    projects = {row["id"]: row for row in client.get("/api/projects").json()}
    assert projects[project["id"]]["active_dataset_id"] == new_id
    assert calls == ["BrewCo", "BrewCo"]


def test_upload_still_succeeds_when_live_quality_is_down(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The service being unreachable never blocks a data upload."""

    async def _down(settings, survey_id, rules=None):
        raise AppError("The bot-detection service could not be reached (ConnectError).", "x", 502)

    monkeypatch.setattr(live_quality, "live_results", _down)
    project = create_project(client)
    body = _upload(
        client, project["id"], tmp_path / "d.sav", pd.DataFrame({"Q1": [1.0], "QOS_SESSION": ["s-1"]})
    )
    assert body["live_quality"]["status"] == "unavailable"
    assert "could not be reached" in body["live_quality"]["message"]
    names = [item["name"] for item in client.get(f"/api/datasets/{body['dataset_id']}").json()["variables"]]
    assert not any(name.startswith("LQ_") for name in names)


def test_untracked_data_is_left_alone(client: TestClient, tmp_path: Path) -> None:
    """Data without QOS ids gets no live_quality note, and a refresh says why it can't run."""
    project = create_project(client)
    body = _upload(client, project["id"], tmp_path / "plain.sav", pd.DataFrame({"Q1": [1.0, 2.0]}))
    assert body["live_quality"] is None
    refused = client.post(f"/api/projects/{project['id']}/live-quality/merge")
    assert refused.status_code == 400 and "QOS_SESSION" in refused.json()["error"]["message"]
