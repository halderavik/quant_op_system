"""Live quality: tracking in Decipher XML, settings, and the results summary."""

import xml.etree.ElementTree as ET

import httpx
import pytest
from fastapi.testclient import TestClient

from app.engines.decipher_tracking import (
    FIELD_LABELS,
    add_tracking,
    check_template_safe,
    tracker_script,
)
from app.services import live_quality
from tests.conftest import create_project

API = "https://bot.example/api/v1"
XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<survey name="S">\n'
    '  <samplesources default="0"><samplesource list="0"><title>Open</title></samplesource></samplesources>\n'
    '  <textarea label="Q1"><title>Why?</title></textarea>\n  <suspend />\n</survey>'
)

QUESTIONNAIRE = {
    "id": "q1",
    "title": "Quality Check",
    "questions": [
        {
            "id": "Q1",
            "type": "single_select",
            "text": "How often do you drink coffee at home?",
            "options": [{"code": 1, "label": "Daily"}, {"code": 2, "label": "Weekly"}],
        },
        {"id": "Q2", "type": "text", "text": "Why do you drink coffee at home?"},
    ],
}


def test_tracker_script_is_safe_for_decipher_templates() -> None:
    """The filled script has no dollar signs, at-sign lines, backticks, or CDATA ends."""
    script = tracker_script("QOS-Test-abc123", API)
    check_template_safe(script)
    assert '"https://bot.example/api/v1"' in script
    assert '"QOS-Test-abc123"' in script
    assert "composite-analyze" in script


@pytest.mark.parametrize("bad", ["x$y", 'q"s', "a--b", " ", "a<b"])
def test_tracking_id_must_be_plain(bad: str) -> None:
    """Ids that could break the script are refused."""
    with pytest.raises(ValueError):
        tracker_script(bad, API)


def test_add_tracking_inserts_script_and_hidden_page() -> None:
    """The script follows the sample sources and the hidden fields close the survey."""
    tracked = add_tracking(XML, "QOS-Test-abc123", API)
    root = ET.fromstring(tracked.split("?>", 1)[1])
    style = root.find("style")
    assert style is not None and style.get("name") == "respview.client.js"
    assert "<script>" in style.text
    labels = [child.get("label") for child in root if child.tag == "text"]
    assert labels == list(FIELD_LABELS)
    assert root[-1].get("label") == FIELD_LABELS[-1]
    assert add_tracking(tracked, "QOS-Test-abc123", API) == tracked


def test_programming_adds_tracking_when_enabled(client: TestClient) -> None:
    """With tracking on, the stored Decipher XML carries the script and the tracking id."""
    project = create_project(client, "Live Check")
    saved = client.post(f"/api/projects/{project['id']}/questionnaires", json=QUESTIONNAIRE)
    assert saved.status_code in {200, 201}, saved.text
    state = client.put(f"/api/projects/{project['id']}/live-quality", json={"enabled": True}).json()
    assert state["enabled"] is True and state["survey_id"] == "Live Check"
    assert state["fielded"] is False
    programmed = client.post(f"/api/projects/{project['id']}/questionnaires/decipher")
    assert programmed.status_code in {200, 201}, programmed.text
    artifacts = client.get(f"/api/projects/{project['id']}/artifacts").json()
    decipher = next(item for item in artifacts if item["type"] == "decipher_survey")
    content = decipher["latest"]["content"]
    assert content["tracking_survey_id"] == state["survey_id"]
    assert "respview.client.js" in content["xml"] and "QOS_SESSION" in content["xml"]
    after = client.get(f"/api/projects/{project['id']}/live-quality").json()
    assert after["decipher"]["tracking_in_xml"] is True
    assert after["fielded"] is True
    assert 'var SURVEY = "Live Check";' in content["xml"]
    # Renaming a fielded project keeps its tracking id so responses stay together.
    client.patch(f"/api/projects/{project['id']}", json={"name": "Renamed Study"})
    renamed = client.get(f"/api/projects/{project['id']}/live-quality").json()
    assert renamed["survey_id"] == "Live Check" and renamed["name_id"] == "Renamed Study"
    # Switching to the new name takes effect at the next programming.
    switched = client.put(
        f"/api/projects/{project['id']}/live-quality",
        json={"enabled": True, "use_project_name": True},
    ).json()
    assert (
        switched["survey_id"] == "Renamed Study"
        and switched["decipher"]["tracking_in_xml"] is False
    )


def test_programming_without_tracking_is_unchanged(client: TestClient) -> None:
    """Tracking stays out unless it is turned on."""
    project = create_project(client, "Plain")
    client.post(f"/api/projects/{project['id']}/questionnaires", json=QUESTIONNAIRE)
    client.post(f"/api/projects/{project['id']}/questionnaires/decipher")
    decipher = next(
        item
        for item in client.get(f"/api/projects/{project['id']}/artifacts").json()
        if item["type"] == "decipher_survey"
    )
    assert "respview.client.js" not in decipher["latest"]["content"]["xml"]


def test_summary_counts_match_rows() -> None:
    """Rows get a status, verdict, and flags; totals are counted from the rows."""
    detailed = {
        "respondents": [
            {
                "session_id": "s1",
                "respondent_id": "R-1",
                "created_at": "2026-11-16T10:00:00+00:00",
                "last_activity": "2026-11-16T10:03:00+00:00",
                "is_bot": True,
                "confidence_score": 0.9,
                "risk_level": "HIGH",
                "flagged_text_responses": 1,
                "timing_speeder": True,
                "text_responses_of_interest": [
                    {
                        "question_preview": "Why?",
                        "response_preview": "asdf",
                        "quality_score": 5,
                        "is_flagged": True,
                        "flag_reasons": {"gibberish": {"is_gibberish": True}},
                    }
                ],
            },
            {
                "session_id": "s2",
                "respondent_id": "R-2",
                "created_at": "2026-11-16T10:05:00+00:00",
                "last_activity": "2026-11-16T10:06:00+00:00",
                "is_bot": False,
                "confidence_score": 0.1,
                "risk_level": "LOW",
            },
            {
                "session_id": "s3",
                "respondent_id": "R-3",
                "created_at": "2020-01-01T00:00:00+00:00",
                "last_activity": "2020-01-01T00:01:00+00:00",
                "risk_level": "unknown",
            },
        ]
    }
    result = live_quality.summarize(
        "QOS-X", {"text_quality_summary": {"total_responses": 3}}, detailed
    )
    totals = result["totals"]
    assert totals == {
        "sessions": 3,
        "in_progress": 0,
        "checked": 2,
        "dropped": 1,
        "bots": 1,
        "flagged": 1,
        "duplicates": 0,
        "speeders": 0,
        "straight_liners": 0,
        "low_quality_text": 1,
    }
    first = result["respondents"][0]
    assert first["session_id"] == "s2" and first["verdict"] == "human"
    bot = next(row for row in result["respondents"] if row["session_id"] == "s1")
    # The service's per-answer timing_speeder is ignored; speeders come from page times.
    assert bot["flags"] == ["Bot-like behaviour", "Low-quality open ends"]
    assert bot["text_details"][0]["reasons"] == ["gibberish"]
    assert (
        next(row for row in result["respondents"] if row["session_id"] == "s3")["verdict"]
        == "pending"
    )


async def test_results_read_both_reports(monkeypatch: pytest.MonkeyPatch, settings) -> None:
    """The service asks for the summary and detailed reports with inactive sessions."""
    seen: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "/reports/detailed/" in request.url.path:
            return httpx.Response(200, json={"respondents": []})
        return httpx.Response(200, json={})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        live_quality.httpx,
        "AsyncClient",
        lambda **kwargs: real(transport=httpx.MockTransport(_handler)),
    )
    live_quality._CACHE.clear()
    result = await live_quality.live_results(settings, "QOS-Y-1")
    assert result["totals"]["sessions"] == 0
    assert all("include_inactive=true" in url for url in seen) and len(seen) == 2


def test_page_times_and_grids_come_from_form_submit_ids() -> None:
    """Repeated sends count once; page times and grid answers are parsed."""
    events = [
        {"event_type": "form_submit", "timestamp": "t1", "element_id": "qos-page:8000"},
        {"event_type": "form_submit", "timestamp": "t1", "element_id": "qos-page:8000"},
        {"event_type": "form_submit", "timestamp": "t1", "element_id": "qos-grid:3,3,3,3"},
        {"event_type": "form_submit", "timestamp": "t2", "element_id": "qos-page:2000"},
        {"event_type": "focus", "timestamp": "t3", "element_id": "qos-page:9"},
    ]
    parsed = live_quality.parse_events(events)
    assert parsed["pages"] == [8000, 2000]
    assert parsed["grids"] == [["3", "3", "3", "3"]]


def test_fast_pages_and_straight_lines_are_flagged() -> None:
    """Under three seconds a page is a speeder; one answer across a grid is straight-lining."""
    detailed = {
        "respondents": [
            {"session_id": "fast", "created_at": "2026-11-16T10:00:00+00:00", "risk_level": "LOW"},
            {"session_id": "slow", "created_at": "2026-11-16T10:01:00+00:00", "risk_level": "LOW"},
        ]
    }
    extras = {
        "fast": {"pages": [1000, 1500, 900], "grids": [["2", "2", "2", "2", "2"]]},
        "slow": {"pages": [20000, 15000, 9000], "grids": [["1", "4", "2", "5", "3"]]},
    }
    result = live_quality.summarize("QOS-Z", {}, detailed, extras)
    fast = next(row for row in result["respondents"] if row["session_id"] == "fast")
    slow = next(row for row in result["respondents"] if row["session_id"] == "slow")
    assert fast["flags"] == ["Straight-lining", "Speeder"]
    assert fast["timing_explanation"] == "Answered 3 pages in 3 seconds."
    assert slow["flags"] == [] and slow["seconds"] == 44.0
    assert result["totals"]["speeders"] == 1 and result["totals"]["straight_liners"] == 1


def test_survey_ids_follow_the_project_name() -> None:
    """Names keep spaces and safe punctuation; dashes and unsafe characters are cleaned."""
    from app.engines.decipher_tracking import survey_id_from_name

    assert survey_id_from_name("BrewCo Live Quality Check") == "BrewCo Live Quality Check"
    assert survey_id_from_name("Demo – Backup") == "Demo - Backup"
    assert survey_id_from_name('a$b"c<d>') == "a b c d"
    assert survey_id_from_name("   ") == "Survey"


def test_trend_buckets_by_hour_and_counts_flags() -> None:
    """Starts are bucketed by hour with empty hours filled."""
    rows = [
        {"started": "2026-11-16T10:05:00+00:00", "flags": ["Speeder"]},
        {"started": "2026-11-16T10:40:00+00:00", "flags": []},
        {"started": "2026-11-16T12:10:00+00:00", "flags": []},
    ]
    result = live_quality.trend(rows)
    assert result["unit"] == "hour"
    assert [(b["started"], b["flagged"]) for b in result["buckets"]] == [(2, 1), (0, 0), (1, 0)]


def test_csv_has_one_row_per_respondent() -> None:
    """The export lists flags and the flagged answers."""
    detailed = {
        "respondents": [
            {
                "session_id": "s1",
                "respondent_id": "R-1",
                "created_at": "2026-11-16T10:00:00+00:00",
                "risk_level": "LOW",
                "flagged_text_responses": 1,
                "text_responses_of_interest": [
                    {
                        "question_preview": "Why?",
                        "response_preview": "xx",
                        "quality_score": 0,
                        "is_flagged": True,
                    }
                ],
            }
        ]
    }
    text = live_quality.results_csv(live_quality.summarize("S", {}, detailed))
    lines = text.strip().splitlines()
    assert lines[0].startswith("respondent_id,session_id")
    assert "R-1" in lines[1] and "Low-quality open ends" in lines[1] and lines[1].endswith("xx")


def test_behaviour_risk_follows_the_score() -> None:
    """A low bot score is low risk, whatever label the service sent."""
    row = live_quality.summarize(
        "S",
        {},
        {"respondents": [{"session_id": "a", "risk_level": "high", "confidence_score": 0.12}]},
    )["respondents"][0]
    assert row["risk"] == "low" and row["service_risk"] == "high"
    assert live_quality.behaviour_risk(0.75) == "high"
    assert live_quality.behaviour_risk(0.55) == "medium"


def test_pasted_answers_get_their_own_flag() -> None:
    """A pasted but sensible answer is flagged as pasted, not as low quality."""

    def row(reasons):
        return {
            "session_id": "s",
            "respondent_id": "R",
            "created_at": "2026-11-16T10:00:00+00:00",
            "is_bot": False,
            "confidence_score": 0.1,
            "flagged_text_responses": 1,
            "text_responses_of_interest": [
                {
                    "question_preview": "Why?",
                    "response_preview": "A long pasted answer.",
                    "quality_score": 80,
                    "is_flagged": True,
                    "flag_reasons": reasons,
                }
            ],
        }

    pasted = live_quality.summarize(
        "S", {}, {"respondents": [row({"pasted": {"pasted_chars": 90}})]}
    )["respondents"][0]
    assert pasted["flags"] == ["Pasted answers"]
    both = live_quality.summarize("S", {}, {"respondents": [row({"pasted": {}, "generic": {}})]})[
        "respondents"
    ][0]
    assert both["flags"] == ["Low-quality open ends", "Pasted answers"]
