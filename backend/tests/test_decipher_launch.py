"""Upload survey.xml to Decipher without calling the live server."""

import json
from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import AppError
from app.main import create_app
from app.schemas.decipher import DecipherProgram
from app.services.decipher_launch import DecipherClient, launcher_from_settings
from tests.conftest import create_project
from tests.test_decipher import _programmed

_API_KEY = "unit-test-decipher-key"
_BASE = "https://selfserve.decipherinc.com/api/v1"


def test_upload_stores_the_path_and_reuses_it(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The first program creates a survey. The next one only replaces survey.xml."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        assert str(request.url).startswith(f"{_BASE}/")
        assert request.headers["x-apikey"] == _API_KEY
        if request.method == "POST":
            assert request.url.path == "/api/v1/rh/companies/self/surveys"
            return httpx.Response(200, json={"path": "selfserve/9/100"})
        assert b"<survey" in request.content
        assert b"overwriteLive" in request.content
        return httpx.Response(200, json={"filename": "survey.xml"})

    _patch_transport(monkeypatch, handler)
    with TestClient(
        create_app(_settings(tmp_path, decipher_api_key=_API_KEY, decipher_api_base=_BASE))
    ) as client:
        project = create_project(client)
        _save_questionnaire(client, project["id"])
        first = client.post(f"/api/projects/{project['id']}/questionnaires/decipher")
        assert first.status_code == 200, first.text
        survey = _decipher_content(client, project["id"])
        assert survey["launch"] == "uploaded"
        assert survey["survey_path"] == "selfserve/9/100"
        assert survey["survey_url"] == "https://selfserve.decipherinc.com/survey/selfserve/9/100"
        assert _API_KEY not in json.dumps(survey)
        second = client.post(f"/api/projects/{project['id']}/questionnaires/decipher")
        assert second.status_code == 200, second.text
    assert calls == [
        "POST /api/v1/rh/companies/self/surveys",
        "PUT /api/v1/surveys/selfserve/9/100/files/survey.xml",
        "PUT /api/v1/surveys/selfserve/9/100/files/survey.xml",
    ]


def test_rejected_xml_is_still_saved(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A Decipher validation error stays on the artifact and the XML remains downloadable."""
    puts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"path": "selfserve/9/100"})
        puts.append(request.url.path)
        return httpx.Response(
            400,
            json={
                "extra": [
                    {"type": "parse", "message": "bad tag"},
                    {"type": "survey", "message": "unknown element"},
                ]
            },
        )

    _patch_transport(monkeypatch, handler)
    with TestClient(
        create_app(_settings(tmp_path, decipher_api_key=_API_KEY, decipher_api_base=_BASE))
    ) as client:
        project = create_project(client)
        _save_questionnaire(client, project["id"])
        programmed = client.post(f"/api/projects/{project['id']}/questionnaires/decipher")
        assert programmed.status_code == 200, programmed.text
        assert programmed.json()["status"] == "completed_with_warnings"
        survey = _decipher_content(client, project["id"])
        assert survey["launch"] == "failed"
        assert survey["survey_path"] == "selfserve/9/100"
        assert "parse: bad tag" in survey["launch_message"]
        assert "survey: unknown element" in survey["launch_message"]
        assert _API_KEY not in json.dumps(survey)
        download = client.get(f"/api/files/{programmed.json()['file_id']}/download")
        assert download.status_code == 200
        assert b"<survey" in download.content
        assert puts == ["/api/v1/surveys/selfserve/9/100/files/survey.xml"]


def test_structure_errors_are_corrected_and_uploaded(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rejected file is corrected from Decipher's messages and uploaded again."""
    puts: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"path": "selfserve/9/100"})
        puts.append(request.content)
        if b"<note" in request.content or b"delphi" not in request.content:
            return httpx.Response(
                400,
                json={
                    "extra": [
                        {
                            "type": "survey",
                            "message": "Surveys at compat 151+ require delphi='1' setting",
                        },
                        {
                            "type": "survey",
                            "message": "This tag (Note) is not permitted inside a Radio tag",
                        },
                    ]
                },
            )
        return httpx.Response(200, json={"filename": "survey.xml"})

    def _broken(document: object) -> DecipherProgram:
        title = getattr(document, "title", "Coffee")
        return DecipherProgram(title=title, xml=_BROKEN, validation_status="passed")

    monkeypatch.setattr("app.services.decipher_program.compile_decipher", _broken)
    _patch_transport(monkeypatch, handler)
    with TestClient(
        create_app(_settings(tmp_path, decipher_api_key=_API_KEY, decipher_api_base=_BASE))
    ) as client:
        project = create_project(client)
        _save_questionnaire(client, project["id"])
        programmed = client.post(f"/api/projects/{project['id']}/questionnaires/decipher")
        assert programmed.status_code == 200, programmed.text
        assert "Corrected" in programmed.json()["summary"]
        survey = _decipher_content(client, project["id"])
        assert survey["launch"] == "uploaded"
        assert any("delphi" in warning for warning in survey["warnings"])
        download = client.get(f"/api/files/{programmed.json()['file_id']}/download")
        assert download.status_code == 200
        assert b"<note" not in download.content
        assert b'delphi="1"' in download.content
        assert b"Ask - all." in download.content
    assert len(puts) == 2


def test_upload_stops_when_decipher_repeats_the_error(tmp_path) -> None:
    """A correction that Decipher still rejects is not uploaded in a loop."""
    puts: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"path": "selfserve/9/100"})
        puts.append(request.content)
        return httpx.Response(
            400,
            json={
                "extra": [
                    {
                        "type": "survey",
                        "message": "Surveys at compat 151+ require delphi='1' setting",
                    }
                ]
            },
        )

    client = DecipherClient(
        _settings(tmp_path, decipher_api_key=_API_KEY, decipher_api_base=_BASE),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(AppError) as caught:
        client.launch('<survey name="Coffee" compat="153"></survey>', "Coffee")
    assert len(puts) == 2
    assert "Corrected before the last attempt" in caught.value.message
    assert 'delphi="1"' in (caught.value.xml or "")


_BROKEN = """<?xml version="1.0" encoding="UTF-8"?>
<survey name="Coffee" alt="Coffee" compat="153">
  <!-- Sample: adults -->
  <radio label="S1">
    <title>What is your age?</title>
    <note>Ask -- all.</note>
    <row label="r1">18-24</row>
  </radio>
</survey>
"""


def test_bad_base_url_does_not_send(tmp_path) -> None:
    """An http URL, or one that omits /api/v1, is refused before any request."""
    seen: list[str] = []
    transport = httpx.MockTransport(
        lambda request: seen.append(str(request.url)) or httpx.Response(500)
    )
    for base in ("http://selfserve.decipherinc.com/api/v1", "https://selfserve.decipherinc.com"):
        client = DecipherClient(
            _settings(tmp_path, decipher_api_key=_API_KEY, decipher_api_base=base),
            transport=transport,
        )
        with pytest.raises(AppError) as caught:
            client.launch("<survey/>", "Coffee")
        assert caught.value.code == "decipher_not_configured"
    assert seen == []


def test_api_key_from_an_error_body_is_removed(tmp_path) -> None:
    """A 401 that echoes the key does not keep the key in the message."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-apikey"] == _API_KEY
        return httpx.Response(401, json={"$error": f"invalid {_API_KEY}"})

    client = DecipherClient(
        _settings(tmp_path, decipher_api_key=_API_KEY, decipher_api_base=_BASE),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(AppError) as caught:
        client.launch("<survey/>", "Coffee")
    assert "API key" in caught.value.message
    assert _API_KEY not in caught.value.message


def _settings(tmp_path, **overrides: str) -> Settings:
    """Build settings that cannot read a real Decipher key from the environment.

    Args:
        tmp_path: Pytest temporary directory.
        **overrides: Decipher fields to replace.

    Returns:
        Isolated settings.
    """
    values = {"decipher_api_base": "", "decipher_api_key": "", "decipher_company": ""}
    values.update(overrides)
    return Settings(
        openai_api_key="",
        database_url=f"sqlite:///{(tmp_path / 'studio.db').as_posix()}",
        storage_root=tmp_path / "storage",
        session_db_path=tmp_path / "sessions.db",
        run_tasks_inline=True,
        cors_origins="http://localhost:5173",
        decipher_api_base=values["decipher_api_base"],
        decipher_api_key=values["decipher_api_key"],
        decipher_company=values["decipher_company"],
    )


def _patch_transport(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    """Point the programmer at a mock Decipher transport.

    Args:
        monkeypatch: Pytest monkeypatch.
        handler: Response factory for one request.
    """
    transport = httpx.MockTransport(handler)

    def _launcher(
        settings: Settings, injected: httpx.BaseTransport | None = None
    ) -> DecipherClient:
        del injected
        launched = launcher_from_settings(settings, transport)
        assert isinstance(launched, DecipherClient)
        return launched

    monkeypatch.setattr("app.services.decipher_program.launcher_from_settings", _launcher)


def _save_questionnaire(client: TestClient, project_id: str) -> None:
    """Store the fixture questionnaire.

    Args:
        client: Test client.
        project_id: Project id.
    """
    saved = client.post(
        f"/api/projects/{project_id}/questionnaires",
        json=_programmed().model_dump(mode="json"),
    )
    assert saved.status_code == 200, saved.text


def _decipher_content(client: TestClient, project_id: str) -> dict:
    """Return the latest Decipher artifact content.

    Args:
        client: Test client.
        project_id: Project id.

    Returns:
        Artifact content.
    """
    artifacts = client.get(f"/api/projects/{project_id}/artifacts").json()
    survey = next(item for item in artifacts if item["type"] == "decipher_survey")
    return survey["latest"]["content"]
