"""Questionnaire translations: translate, review, sign off, and export."""

from fastapi.testclient import TestClient

from app.schemas.questionnaire import Option, Question, Questionnaire
from app.services import translation
from app.services.translation import source_segments, translated_questionnaire
from tests.conftest import create_project


def _document(q1_text: str = "Which brand do you buy?") -> Questionnaire:
    return Questionnaire(
        id="t",
        title="Coffee Study",
        questions=[
            Question(
                id="Q1",
                type="single_select",
                text=q1_text,
                instruction="Select one.",
                programmer_notes=["RANDOMIZE"],
                options=[Option(code=1, label="Alpha"), Option(code=2, label="Other")],
            ),
            Question(
                id="Q2",
                type="grid",
                text="How much do you agree?",
                matrix_items=["It tastes good", "It is good value"],
                options=[Option(code=1, label="Disagree"), Option(code=2, label="Agree")],
            ),
        ],
    )


def _fake_translator(calls: list[str]):
    async def run_structured(settings, *, prompt, output_type, **kwargs):
        calls.append(prompt)
        lines = prompt.split("SEGMENTS (key<TAB>text):\n", 1)[1].splitlines()
        items = []
        for line in lines:
            key, text = line.split("\t", 1)
            if text == "Alpha":
                items.append({"key": key, "text": text})  # brand names stay as written
            else:
                items.append({"key": key, "text": f"DE:{text}"})
        return output_type.model_validate({"items": items})

    return run_structured


def _setup(client: TestClient, monkeypatch, calls: list[str]) -> str:
    import app.agents.sdk as sdk

    monkeypatch.setattr(sdk, "run_structured", _fake_translator(calls))
    monkeypatch.setattr(type(client.app.state.settings), "llm_configured", property(lambda _: True))
    project = create_project(client)
    saved = client.post(
        f"/api/projects/{project['id']}/questionnaires", json=_document().model_dump(mode="json")
    )
    assert saved.status_code == 200, saved.text
    return project["id"]


def test_segments_cover_what_respondents_see_and_not_programmer_notes() -> None:
    keys = [segment["key"] for segment in source_segments(_document())]
    assert keys == [
        "title",
        "Q1.text",
        "Q1.instruction",
        "Q1.opt.1",
        "Q1.opt.2",
        "Q2.text",
        "Q2.opt.1",
        "Q2.opt.2",
        "Q2.item.1",
        "Q2.item.2",
    ]
    content = {"segments": [{"key": "Q2.item.2", "text": "Gutes Preis-Leistungs-Verhältnis"}]}
    translated = translated_questionnaire(_document(), content)
    assert translated.questions[1].matrix_items == [
        "It tastes good",
        "Gutes Preis-Leistungs-Verhältnis",
    ]
    assert translated.questions[0].programmer_notes == ["RANDOMIZE"]


def test_translate_review_sign_off_and_retranslate_after_a_change(
    client: TestClient, monkeypatch
) -> None:
    calls: list[str] = []
    project_id = _setup(client, monkeypatch, calls)
    added = client.post(
        f"/api/projects/{project_id}/translations",
        json={"language": "German (Germany)", "notes": "Use Sie."},
    )
    assert added.status_code == 201, added.text
    body = added.json()
    assert body["translated"] == 10 and body["missing"] == 0 and body["status"] == "draft"
    assert "TRANSLATOR NOTES: Use Sie." in calls[0]
    artifact_id = body["artifact_id"]

    detail = client.get(f"/api/projects/{project_id}/translations/{artifact_id}").json()
    alpha = next(s for s in detail["segments"] if s["key"] == "Q1.opt.1")
    assert alpha["text"] == "Alpha" and alpha["state"] == "ok"

    edited = client.put(
        f"/api/projects/{project_id}/translations/{artifact_id}/segments",
        json={"key": "Q1.text", "text": "Welche Marke kaufen Sie?"},
    ).json()
    assert edited["edited"] == 1

    approved = client.post(
        f"/api/projects/{project_id}/translations/{artifact_id}/approve",
        json={"reviewer": "Local reviewer"},
    ).json()
    assert approved["status"] == "approved" and approved["approved_by"] == "Local reviewer"

    # The source wording changes: the language needs review and only Q1.text is redone.
    client.post(
        f"/api/projects/{project_id}/questionnaires",
        json=_document("Which brand do you buy most often?").model_dump(mode="json"),
    )
    listed = client.get(f"/api/projects/{project_id}/translations").json()["languages"][0]
    assert listed["status"] == "needs_review" and listed["source_changed"] == 1
    refused = client.post(
        f"/api/projects/{project_id}/translations/{artifact_id}/approve",
        json={"reviewer": "Local reviewer"},
    )
    assert refused.status_code == 400
    redone = client.post(
        f"/api/projects/{project_id}/translations/{artifact_id}/translate", json={}
    ).json()
    assert redone["translated"] == 1 and redone["status"] == "draft"
    assert "Use Sie." in calls[-1]  # the language keeps its translator notes


def test_export_word_and_xml(client: TestClient, monkeypatch) -> None:
    project_id = _setup(client, monkeypatch, [])
    artifact_id = client.post(
        f"/api/projects/{project_id}/translations", json={"language": "German"}
    ).json()["artifact_id"]
    word = client.post(f"/api/projects/{project_id}/translations/{artifact_id}/export/docx")
    assert word.status_code == 200, word.text
    assert word.json()["warning"].startswith("This language is not signed off")
    xml = client.post(f"/api/projects/{project_id}/translations/{artifact_id}/export/xml")
    assert xml.status_code == 200, xml.text
    assert xml.json()["filename"] == "survey_German.xml"
    bad = client.post(f"/api/projects/{project_id}/translations/{artifact_id}/export/pptx")
    assert bad.status_code == 400


def test_translation_needs_a_model(client: TestClient) -> None:
    project = create_project(client)
    client.post(
        f"/api/projects/{project['id']}/questionnaires", json=_document().model_dump(mode="json")
    )
    response = client.post(
        f"/api/projects/{project['id']}/translations", json={"language": "French"}
    )
    assert response.status_code == 400
    assert translation.ARTIFACT == "translation"
