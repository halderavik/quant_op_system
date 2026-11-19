"""Adding live bot and fraud tracking to a Decipher survey XML programmed elsewhere."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.engines.decipher_tracking import (
    add_tracking,
    has_tracking,
    page_breaks,
    parse_survey,
    remove_tracking,
)
from app.main import create_app
from tests.conftest import create_project

API = "https://bot.example/api/v1"

# Shaped like a programmer's file: undeclared ss: and builder: prefixes, the survey's
# own page script, a loop, and a block only some respondents see.
SURVEY = """<?xml version="1.0" encoding="UTF-8"?>
<survey alt="Coffee Tracker" name="Survey" builder:wizardCompleted="1" ss:disableBackButton="1" state="testing">
<samplesources default="1">
  <samplesource list="1"><title>Open</title><exit cond="terminated">Bye</exit></samplesource>
</samplesources>
<style mode="after" name="respview.client.js" wrap="ready"><![CDATA[
if (a < b) { console.log("house script"); }
]]></style>
<radio label="S1"><title>Do you drink coffee?</title><row label="r1">Yes</row><row label="r2">No</row></radio>
<suspend/>
<block label="BLK_Fans" cond="S1.r1">
  <radio label="S2"><title>How often?</title><row label="r1">Daily</row><row label="r2">Weekly</row></radio>
  <suspend/>
</block>
<loop label="L1" vars="brand">
  <block label="B_L1">
    <radio label="Q1_[loopvar: label]"><title>Rate [loopvar: brand]</title><row label="r1">Good</row><row label="r2">Bad</row></radio>
    <suspend/>
  </block>
  <looprow label="1"><loopvar name="brand">BrewCo</loopvar></looprow>
</loop>
<text label="Q2"><title>Anything else?</title></text>
<suspend/>
<radio label="Q3"><title>Would you recommend it?</title><row label="r1">Yes</row><row label="r2">No</row></radio>
<suspend/>
</survey>
"""


def _upload(
    client: TestClient, project_id: str, name: str = "coffee.xml", body: str = SURVEY
) -> str:
    response = client.post(
        f"/api/projects/{project_id}/files",
        files={"file": (name, body.encode(), "application/xml")},
    )
    assert response.status_code == 201, response.text
    return response.json()["file_id"]


def _survey_artifact(client: TestClient, project_id: str) -> dict:
    return next(
        item
        for item in client.get(f"/api/projects/{project_id}/artifacts").json()
        if item["type"] == "decipher_survey"
    )["latest"]


def test_programmer_xml_parses_with_undeclared_prefixes() -> None:
    """Decipher's undeclared ss: and builder: prefixes don't stop the check."""
    assert parse_survey(SURVEY).tag == "survey"


def test_page_breaks_skip_loops_and_conditional_blocks() -> None:
    """Only breaks every respondent reaches can hold the in-survey check."""
    breaks = page_breaks(SURVEY)
    assert len(breaks) == 3  # after S1, after Q2, after Q3
    before = [SURVEY[: match.start()] for match in breaks]
    assert before[0].rstrip().endswith("</radio>") and "S2" not in before[0]
    assert "Q2" in before[1] and "Q3" not in before[1]


def test_tracking_adds_to_the_surveys_own_scripts_and_comes_off_cleanly() -> None:
    """The tracker uses mode="after", and removing it gives back the original file."""
    rules = {"terminate": True, "after_page": 2, "privacy_text": "We check answers."}
    tracked = add_tracking(SURVEY, "Coffee Tracker", API, rules=rules)
    assert '<style mode="after" name="respview.client.js"><![CDATA[' in tracked
    assert "house script" in tracked
    # The early check sits after the second page everyone sees, not in the loop or block.
    early = tracked.index('label="QOS_EARLY"')
    assert tracked.index('label="Q2"') < early < tracked.index('label="Q3"')
    assert has_tracking(tracked)
    assert remove_tracking(tracked) == SURVEY


def test_upload_adds_tracking_and_saves_the_survey(client: TestClient) -> None:
    """An uploaded XML gets tracking, becomes the project's survey, and turns tracking on."""
    project = create_project(client, "Coffee Tracker")
    file_id = _upload(client, project["id"])
    response = client.post(
        f"/api/projects/{project['id']}/live-quality/xml", json={"file_id": file_id}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (
        "Added live bot and fraud tracking to coffee.xml (Coffee Tracker, 5 questions)"
        in body["summary"]
    )
    assert body["state"]["enabled"] is True
    assert body["state"]["decipher"]["tracking_in_xml"] is True
    assert body["state"]["decipher"]["source_file"] == "coffee.xml"
    saved = _survey_artifact(client, project["id"])["content"]
    assert saved["source"] == "uploaded_xml" and saved["survey_path"] is None
    assert saved["launch"] == "not_configured"
    downloaded = client.get(f"/api/files/{body['file_id']}/download").text
    assert 'label="QOS_SESSION"' in downloaded and "house script" in downloaded
    assert remove_tracking(downloaded) == SURVEY


def test_a_file_that_is_not_a_survey_is_refused(client: TestClient) -> None:
    """Any other XML is refused with a plain explanation, and nothing is saved."""
    project = create_project(client)
    file_id = _upload(client, project["id"], "notes.xml", "<notes><note>hi</note></notes>")
    response = client.post(
        f"/api/projects/{project['id']}/live-quality/xml", json={"file_id": file_id}
    )
    assert response.status_code >= 400
    assert "not a Decipher survey XML" in response.json()["error"]["message"]
    kinds = {item["type"] for item in client.get(f"/api/projects/{project['id']}/artifacts").json()}
    assert "decipher_survey" not in kinds


def test_tracking_added_before_is_replaced_not_doubled(client: TestClient) -> None:
    """Uploading a file that already has Quant OS tracking re-applies it once."""
    project = create_project(client, "Coffee Tracker")
    old = add_tracking(SURVEY, "Old Id", API)
    file_id = _upload(client, project["id"], "tracked.xml", old)
    body = client.post(
        f"/api/projects/{project['id']}/live-quality/xml", json={"file_id": file_id}
    ).json()
    assert "replaced with the current settings" in body["summary"]
    xml = _survey_artifact(client, project["id"])["content"]["xml"]
    assert xml.count('label="QOS_SESSION"') == 1 and "Old Id" not in xml


def test_upload_from_an_uploaded_xml_creates_a_new_survey(settings: Settings, monkeypatch) -> None:
    """With a Decipher key the upload waits for a click, then creates a new test survey."""
    keyed = settings.model_copy(update={"decipher_api_key": "test-key"})
    calls: list[str | None] = []

    class _Launcher:
        def launch(self, xml: str, name: str, survey_path: str | None = None):
            from app.services.decipher_launch import LaunchResult

            calls.append(survey_path)
            return LaunchResult(
                launched=True,
                message="Uploaded to Decipher at selfserve/1/2.",
                survey_path="selfserve/1/2",
                survey_url="https://selfserve.decipherinc.com/survey/selfserve/1/2",
                xml=xml,
                fixes=[],
            )

    monkeypatch.setattr(
        "app.services.decipher_program.launcher_from_settings", lambda _s: _Launcher()
    )
    with TestClient(create_app(keyed)) as client:
        project = create_project(client, "Coffee Tracker")
        file_id = _upload(client, project["id"])
        body = client.post(
            f"/api/projects/{project['id']}/live-quality/xml", json={"file_id": file_id}
        ).json()
        assert "create a new Decipher test survey" in body["summary"]
        assert calls == []  # nothing is sent before the click
        assert body["state"]["decipher"]["awaiting_upload"] is True
        uploaded = client.post(f"/api/projects/{project['id']}/decipher/upload").json()
        assert uploaded["launch"] == "uploaded"
        assert calls == [None]  # a new survey, never an existing path
        # Re-adding tracking to the same file keeps the test survey made from it.
        again = client.post(
            f"/api/projects/{project['id']}/live-quality/xml", json={"file_id": file_id}
        ).json()
        assert again["survey_path"] == "selfserve/1/2"


def test_chat_with_an_attached_xml_adds_tracking(client: TestClient) -> None:
    """ "Add our bot detection" with a survey XML attached runs without a route call."""
    project = create_project(client, "Coffee Tracker")
    file_id = _upload(client, project["id"])
    response = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": "Add our bot detection to this survey", "file_ids": [file_id]},
    )
    assert response.status_code == 201, response.text
    task = client.get(f"/api/tasks/{response.json()['task_id']}").json()
    assert task["status"] in {"completed", "completed_with_warnings"}, (
        task["contract"].get("missing_required"),
        task["contract"].get("intent"),
        task.get("result"),
    )
    reply = client.get(f"/api/conversations/{project['conversation_id']}/messages").json()[-1]
    assert "Added live bot and fraud tracking to coffee.xml" in reply["content"]
    assert _survey_artifact(client, project["id"])["content"]["source"] == "uploaded_xml"
