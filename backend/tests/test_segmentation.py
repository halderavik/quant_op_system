"""Segmentation: compare solutions, profile, typing tool, and saving segments to the data."""

from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
import pyreadstat
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.engines.segmentation import classify, compare_solutions
from tests.conftest import create_project


def _three_groups(n: int = 900, seed: int = 3) -> pd.DataFrame:
    """Three clear groups on four ratings, plus a noise variable."""
    rng = np.random.default_rng(seed)
    centres = np.array([[9, 2, 8, 5], [2, 9, 3, 5], [5, 5, 5, 9]], dtype=float)
    group = rng.integers(0, 3, n)
    values = centres[group] + rng.normal(0, 0.8, (n, 4))
    frame = pd.DataFrame(values.round(0).clip(0, 10), columns=["PRICE", "QUALITY", "ECO", "BRAND"])
    frame["NOISE"] = rng.normal(5, 2, n).round(0)
    frame.loc[:4, "PRICE"] = np.nan  # five respondents are left out
    return frame


def test_three_clear_groups_are_recommended_and_typed() -> None:
    frame = _three_groups()
    result = compare_solutions(frame, ["PRICE", "QUALITY", "ECO", "BRAND", "NOISE"], [2, 3, 4, 5])
    assert result["recommended"] == 3
    assert result["dropped"] == 5 and result["base"] == len(frame) - 5
    three = next(s for s in result["solutions"] if s["k"] == 3)
    assert three["stability"] > 0.9 and three["silhouette"] > 0.4
    shares = [p["share"] for p in three["profiles"]]
    assert shares == sorted(shares, reverse=True) and abs(sum(shares) - 1) < 0.01
    assert all(p["top"][0]["variable"] != "NOISE" for p in three["profiles"])
    typing = three["typing"]
    assert typing["accuracy"] >= 0.95 and len(typing["variables"]) <= 3
    assert "NOISE" not in typing["variables"]
    # The published coefficients reproduce each respondent's segment.
    complete = frame.dropna()
    hits = sum(
        classify(typing, {name: row[name] for name in typing["variables"]}) == segment
        for (_, row), segment in zip(complete.iterrows(), three["assignments"], strict=True)
    )
    assert hits / len(complete) > 0.95


def test_bad_inputs_are_refused() -> None:
    frame = _three_groups(60)
    for variables, k in ((["PRICE"], [3]), (["PRICE", "MISSING"], [3]), (["PRICE", "ECO"], [6])):
        try:
            compare_solutions(frame, variables, k)
        except Exception as exc:  # noqa: BLE001
            assert getattr(exc, "status_code", 400) == 400
        else:
            raise AssertionError(f"{variables} {k} should be refused")


def test_segmentation_journey(client: TestClient, tmp_path: Path) -> None:
    project = create_project(client)
    path = tmp_path / "attitudes.sav"
    pyreadstat.write_sav(
        _three_groups(),
        path,
        column_labels=["Price matters", "Quality matters", "Eco matters", "Brand matters", "Noise"],
    )
    with path.open("rb") as handle:
        uploaded = client.post(
            f"/api/projects/{project['id']}/files",
            files={"file": (path.name, handle, "application/octet-stream")},
        )
    assert uploaded.status_code == 201, uploaded.text
    names = [
        v["name"]
        for v in client.get(f"/api/projects/{project['id']}/segmentation/variables").json()
    ]
    assert "PRICE" in names

    run = client.post(
        f"/api/projects/{project['id']}/segmentation",
        json={"variables": ["PRICE", "QUALITY", "ECO", "BRAND"], "k_min": 2, "k_max": 4},
    )
    assert run.status_code == 201, run.text
    body = run.json()
    assert body["chosen"] == 3 and "assignments" not in body["solutions"][0]
    artifact_id = body["artifact_id"]

    renamed = client.patch(
        f"/api/projects/{project['id']}/segmentation/{artifact_id}",
        json={"names": {"1": "Value seekers"}},
    ).json()
    chosen = next(s for s in renamed["solutions"] if s["k"] == 3)
    assert chosen["profiles"][0]["name"] == "Value seekers"

    tool = client.post(f"/api/projects/{project['id']}/segmentation/{artifact_id}/typing-tool")
    assert tool.status_code == 200, tool.text
    download = client.get(f"/api/files/{tool.json()['file_id']}/download")
    sheet = load_workbook(BytesIO(download.content)).active
    formulas = [
        c.value
        for row in sheet.iter_rows()
        for c in row
        if isinstance(c.value, str) and c.value.startswith("=")
    ]
    assert any("INDEX(" in f for f in formulas) and len(formulas) == 4

    saved = client.post(f"/api/projects/{project['id']}/segmentation/{artifact_id}/save-to-data")
    assert saved.status_code == 200, saved.text
    assert saved.json()["variable"] == "SEG_3" and saved.json()["version"] == 2
    variables = client.get(f"/api/projects/{project['id']}/segmentation/variables").json()
    assert any(v["name"] == "SEG_3" for v in variables)
