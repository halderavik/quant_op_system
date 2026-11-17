"""Quality rules: defaults, editing, how they change flags, and what reaches the Decipher survey."""

import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from app.engines.decipher_tracking import (
    add_tracking,
    check_template_safe,
    survey_token,
    tracker_script,
)
from app.services import live_quality
from app.services.quality_rules import QualityRules
from tests.conftest import create_project

API = "https://bot.example/api/v1"

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

SURVEY_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<survey name="S">\n'
    '  <samplesources default="0"><samplesource list="0"><title>Open</title></samplesource></samplesources>\n'
    '  <block label="B">\n'
    '    <radio label="Q1"><title>How often?</title><row label="r1">Daily</row></radio>\n    <suspend />\n'
    '    <textarea label="Q2"><title>Why?</title></textarea>\n    <suspend />\n'
    '    <textarea label="Q3"><title>What else?</title></textarea>\n    <suspend />\n'
    "  </block>\n</survey>"
)


def _respondent(**overrides):
    base = {
        "session_id": "s",
        "respondent_id": "R",
        "created_at": "2026-11-16T10:00:00+00:00",
        "is_bot": False,
        "confidence_score": 0.2,
        "risk_level": "LOW",
    }
    base.update(overrides)
    return base


def _row(item, extras=None, **rules):
    result = live_quality.summarize(
        "S", {}, {"respondents": [item]}, extras, rules=QualityRules(**rules)
    )
    return result["respondents"][0]


def test_rules_api_defaults_save_validate_and_reset(client: TestClient) -> None:
    """Projects start on the defaults; edits are validated, listed as changes, and can be reset."""
    project = create_project(client, "Rules Study")
    url = f"/api/projects/{project['id']}/live-quality/rules"
    state = client.get(url).json()
    assert state["rules"] == state["defaults"] and state["changed"] == []
    assert state["rules"]["bot_threshold"] == 0.7 and state["rules"]["terminate_in_survey"] is True
    assert "honeypot" in state["bot_signals"] and "generic" in state["text_reasons"]
    edited = {**state["rules"], "bot_threshold": 0.8, "terminate_signals": ["honeypot"]}
    saved = client.put(url, json=edited).json()
    assert saved["rules"]["bot_threshold"] == 0.8
    assert sorted(saved["changed"]) == ["bot_threshold", "terminate_signals"]
    assert client.put(url, json={**edited, "bot_signals": ["telepathy"]}).status_code == 422
    assert (
        client.put(url, json={**edited, "privacy_text": "It costs 5 dollars: $5."}).status_code
        == 422
    )
    assert client.put(url, json={**edited, "bot_threshold": 1.5}).status_code == 422
    reset = client.delete(url).json()
    assert reset["rules"] == reset["defaults"]


def test_bot_rules_use_base_score_and_enabled_signals() -> None:
    """Enabled decisive signals make a bot; the threshold applies to the score before them."""
    item = _respondent(
        is_bot=True,
        confidence_score=0.85,
        flagged_patterns={"base_score": 0.45, "decisive_codes": ["honeypot"]},
    )
    assert _row(item)["verdict"] == "bot" and _row(item)["bot_signals"] == ["honeypot"]
    off = _row(item, bot_signals=["automation"])
    assert off["verdict"] == "human" and "Bot-like behaviour" not in off["flags"]
    assert _row(item, bot_signals=[], bot_threshold=0.4)["verdict"] == "bot"
    legacy = _respondent(is_bot=True, confidence_score=0.75)  # older service rows have no codes
    assert (
        _row(legacy)["verdict"] == "bot" and _row(legacy, bot_threshold=0.8)["verdict"] == "human"
    )


def test_speed_text_and_fraud_rules() -> None:
    """Speeder, straight-lining, open-end, fraud, and data-centre flags follow the rules."""
    timed = _respondent(confidence_score=0.1)
    extras = {"s": {"pages": [5000, 5000, 5000, 5000], "grids": [["3", "3", "3"]]}}
    row = _row(timed, extras)
    assert "Speeder" not in row["flags"] and "Straight-lining" in row["flags"]
    row = _row(timed, extras, speeder_page_seconds=6, straightline_min_rows=4)
    assert "Speeder" in row["flags"] and "Straight-lining" not in row["flags"]

    generic = _respondent(
        flagged_text_responses=1,
        text_responses_of_interest=[
            {
                "question_preview": "Why?",
                "response_preview": "good",
                "quality_score": 10,
                "is_flagged": True,
                "flag_reasons": {"generic": {}},
            }
        ],
    )
    assert "Low-quality open ends" in _row(generic)["flags"]
    assert "Low-quality open ends" not in _row(generic, text_reasons=["gibberish"])["flags"]

    risky = _respondent(fraud_score=0.6, fraud_flag_reasons={"datacenter_ip": {"provider": "AWS"}})
    assert (
        "High fraud risk" not in _row(risky)["flags"] and "Data-centre IP" in _row(risky)["flags"]
    )
    assert "High fraud risk" in _row(risky, fraud_threshold=0.5)["flags"]
    assert "Data-centre IP" not in _row(risky, flag_datacenter=False)["flags"]


def test_xml_gets_privacy_notice_token_and_in_survey_termination() -> None:
    """Termination goes after the chosen page; the notice opens the survey; the token is in the script."""
    rules = {
        "terminate": True,
        "after_page": 2,
        "signals": ["honeypot", "automation"],
        "privacy_text": "We check how answers are entered & keep them genuine.",
    }
    xml = add_tracking(SURVEY_XML, "Rules Study", API, token="ab12" * 8, rules=rules)
    root = ET.fromstring(xml.split("?>", 1)[1])
    labels = [element.get("label") for element in root.iter() if element.get("label")]
    assert labels.index("QOS_privacy") < labels.index("Q1")
    assert (
        labels.index("Q2")
        < labels.index("QOS_EARLY")
        < labels.index("QOS_bot_term")
        < labels.index("Q3")
    )
    term = next(root.iter("term"))
    assert term.get("cond") == "QOS_EARLY.val and QOS_EARLY.val.strip() == 'bot'"
    assert 'var TOKEN = "' + "ab12" * 8 + '";' in xml
    assert '"signals": ["honeypot", "automation"]' in xml and '"terminate": true' in xml
    assert "&amp; keep them genuine" in xml
    plain = add_tracking(SURVEY_XML, "Rules Study", API, rules={"terminate": True, "after_page": 9})
    assert "QOS_EARLY" not in plain and "QOS_privacy" not in plain  # too few pages; no notice
    with pytest.raises(ValueError):
        tracker_script("Rules Study", API, token="not-hex!")


def test_survey_token_matches_the_service() -> None:
    """Same HMAC as the bot-detection service; no secret means no token."""
    import hashlib
    import hmac

    expected = hmac.new(b"s3cret", b"Rules Study", hashlib.sha256).hexdigest()[:32]
    assert survey_token("Rules Study", "s3cret") == expected
    assert survey_token("Rules Study", "") == ""


def test_filled_tracker_is_valid_javascript() -> None:
    """The filled script parses (checked with Node when it is installed)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not installed")
    script = tracker_script(
        "Rules Study", API, token="ab" * 16, rules={"terminate": True, "signals": ["honeypot"]}
    )
    check_template_safe(script)
    body = re.search(r"<script>([\s\S]*)</script>", script).group(1)
    result = subprocess.run(
        [node, "-e", "new Function(require('fs').readFileSync(0, 'utf8'))"],
        input=body,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_programming_writes_the_project_rules(client: TestClient) -> None:
    """Saved in-survey rules reach the programmed XML."""
    project = create_project(client, "Rules Programming")
    client.post(f"/api/projects/{project['id']}/questionnaires", json=QUESTIONNAIRE)
    client.put(f"/api/projects/{project['id']}/live-quality", json={"enabled": True})
    url = f"/api/projects/{project['id']}/live-quality/rules"
    rules = {
        **client.get(url).json()["rules"],
        "terminate_after_page": 1,
        "terminate_signals": ["honeypot"],
    }
    assert client.put(url, json=rules).status_code == 200
    assert client.post(f"/api/projects/{project['id']}/questionnaires/decipher").status_code in {
        200,
        201,
    }
    artifacts = client.get(f"/api/projects/{project['id']}/artifacts").json()
    xml = next(item for item in artifacts if item["type"] == "decipher_survey")["latest"][
        "content"
    ]["xml"]
    assert "QOS_EARLY" in xml and "QOS_bot_term" in xml and "QOS_privacy" in xml
    assert '"signals": ["honeypot"]' in xml
