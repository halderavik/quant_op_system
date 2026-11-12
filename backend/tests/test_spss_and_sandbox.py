"""SPSS ingest, path checks, and the labelled subprocess fallback."""

from pathlib import Path

import pandas as pd
import pyreadstat
import pytest

from app.config import Settings
from app.engines.spss import is_text_column, read_spss
from app.errors import AppError
from app.sandbox.runner import docker_command, run_script
from app.services.storage import Storage


def _sav(path: Path) -> None:
    """Write a tiny labelled SAV file.

    Args:
        path: Destination.
    """
    frame = pd.DataFrame({"respondent_id": [1, 2], "trust": [1, 99], "weight_main": [1.0, 0.5]})
    pyreadstat.write_sav(
        frame,
        path,
        column_labels=["Respondent", "Overall trust", "Weight"],
        variable_value_labels={"trust": {1: "Very low", 5: "Very high"}},
        missing_ranges={"trust": [{"lo": 98, "hi": 99}]},
    )


def test_sav_keeps_labels_and_missing_codes(tmp_path: Path) -> None:
    """Labels, user-missing codes, and the row count survive ingest."""
    path = tmp_path / "survey_small.sav"
    _sav(path)
    frame, variables, weights = read_spss(path)
    trust = next(item for item in variables if item["name"] == "trust")
    assert frame.shape[0] == 2
    assert trust["value_labels"]["1.0"] == "Very low" or trust["value_labels"]["1"] == "Very low"
    assert 99 in trust["user_missing_values"] or 99.0 in trust["user_missing_values"]
    assert "weight_main" in weights
    assert list(frame["trust"])[1] == 99 or list(frame["trust"])[1] == 99.0


def test_string_variables_are_text(tmp_path: Path) -> None:
    """String columns are text under pandas 3, where they are not ``object`` dtype."""
    path = tmp_path / "text.sav"
    frame = pd.DataFrame(
        {"uuid": ["a1", "b2", "c3"], "Q1": [1.0, 2.0, 1.0], "Q2oe": ["fast", "", "cheap"]}
    )
    pyreadstat.write_sav(frame, str(path))
    _, variables, _ = read_spss(path)
    kinds = {item["name"]: item["is_text"] for item in variables}
    assert kinds == {"uuid": True, "Q1": False, "Q2oe": True}


def test_is_text_column_without_storage_type() -> None:
    """The dtype fallback accepts both the pandas 3 string dtype and object."""
    assert is_text_column(pd.Series(["a", "b"], dtype="string"))
    assert is_text_column(pd.Series(["a", None], dtype=object))
    assert not is_text_column(pd.Series([1.0, 2.0]))
    assert is_text_column(pd.Series([1.0]), "string")
    assert not is_text_column(pd.Series(["1"], dtype=object), "double")


def test_malformed_sav_is_readable(tmp_path: Path) -> None:
    """A corrupt file raises a user-facing error."""
    path = tmp_path / "bad.sav"
    path.write_bytes(b"this is not an spss file")
    with pytest.raises(AppError) as caught:
        read_spss(path)
    assert caught.value.code == "bad_spss"


def test_path_traversal_is_rejected(tmp_path: Path) -> None:
    """Paths outside the project root are rejected."""
    storage = Storage(
        Settings(storage_root=tmp_path / "storage", cors_origins="http://localhost:5173")
    )
    with pytest.raises(AppError) as caught:
        storage.resolve("project-1", "../secrets.txt")
    assert caught.value.code == "path_traversal"


def test_subprocess_fallback_hides_the_key_and_blocks_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fallback is not described as secure, and it cannot see the API key."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak")
    settings = Settings(
        openai_api_key="sk-should-not-leak",
        storage_root=tmp_path,
        cors_origins="http://localhost:5173",
        sandbox_timeout_seconds=20,
    )
    secret = tmp_path / "secret.txt"
    secret.write_text("hidden", encoding="utf-8")
    job = tmp_path / "job"
    result = run_script(
        settings,
        job,
        "import os\nprint('KEY=' + str(os.environ.get('OPENAI_API_KEY')))\n"
        "print('ANTHROPIC=' + str(os.environ.get('ANTHROPIC_API_KEY')))\n",
    )
    assert result["isolation"] in {"subprocess_fallback", "docker"}
    assert "sk-should-not-leak" not in result["stdout"]
    assert "sk-ant-should-not-leak" not in result["stdout"]
    if result["isolation"] == "subprocess_fallback":
        assert result["warning"]
        assert "not a secure sandbox" in result["warning"]
        escaped = run_script(settings, job, f"open(r'{secret}', 'r').read()\n")
        assert escaped["exit_code"] != 0


def test_docker_command_has_no_network_and_no_key() -> None:
    """The docker argv disables the network and does not pass the API key."""
    settings = Settings(
        openai_api_key="sk-should-not-leak",
        storage_root=Path("."),
        cors_origins="http://localhost:5173",
    )
    command = docker_command(settings, Path("C:/tmp/job"), "main.py")
    assert "--network" in command
    assert "none" in command
    assert "sk-should-not-leak" not in command
