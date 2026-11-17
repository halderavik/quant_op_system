"""Open-end coding through the Ad Hoc AutoCoder, with a fake model."""

from pathlib import Path

import pandas as pd
import pyreadstat
import pytest
from adhoc_autocoder.models import (
    ClassifiedCode,
    ConceptBatch,
    ConceptsForResponse,
    ConsolidatedCodes,
    NetPlan,
    NetSpec,
    ProposedLeaf,
    ProposedLeaves,
    ResponseDecision,
)

from app.agents.intent import build_contract
from app.config import Settings
from tests.conftest import create_project

_ANSWERS = [
    "Too expensive for what you get",
    "The coffee tastes great",
    "",
    "Great taste but the price is high",
    "Expensive machine",
    "Lovely taste every morning",
]


def _themes(text: str) -> list[str]:
    lowered = text.lower()
    found = []
    if "expensive" in lowered or "price" in lowered:
        found.append("price is too high")
    if "taste" in lowered:
        found.append("good taste")
    return found


class _FakeLLM:
    """Answers each AutoCoder schema from keywords; never calls a network."""

    def __init__(self, conf, cache_dir) -> None:
        self.calls = 0

    async def close(self) -> None:
        return None

    async def request(self, instructions, data, schema):
        self.calls += 1
        if schema is NetPlan:
            return NetPlan(
                nets=[
                    NetSpec(name="PRODUCT", description="Taste and quality"),
                    NetSpec(name="VALUE", description="Price and value"),
                ],
                rationale="Reasons for a recommendation score.",
            )
        if schema is ConceptBatch:
            return ConceptBatch(
                responses=[
                    ConceptsForResponse(
                        response_id=item["response_id"], concepts=_themes(item["response_text"])
                    )
                    for item in data["responses"]
                ]
            )
        if schema is ProposedLeaves:
            leaves = []
            for cluster in data["clusters"]:
                words = " ".join(cluster["concept_examples"]).lower()
                price = "price" in words
                leaves.append(
                    ProposedLeaf(
                        cluster_id=cluster["cluster_id"],
                        net="VALUE" if price else "PRODUCT",
                        subnet="PRICE" if price else "TASTE",
                        code_name="Too expensive" if price else "Good taste",
                        definition="Price is too high" if price else "Likes the taste",
                        include="price" if price else "taste",
                        exclude="",
                        evidence_response_ids=cluster["evidence_response_ids"][:1],
                    )
                )
            return ProposedLeaves(leaves=leaves)
        if schema is ConsolidatedCodes:
            return ConsolidatedCodes(codes=[])
        if schema is ResponseDecision:
            text = data["response_text"].lower()
            chosen = [
                ClassifiedCode(code_id=item["code_id"], confidence=0.9)
                for item in data["candidate_codes"]
                if (
                    "expensive" in item["code_name"].lower()
                    and ("expensive" in text or "price" in text)
                )
                or ("taste" in item["code_name"].lower() and "taste" in text)
            ]
            return ResponseDecision(
                assigned_codes=chosen,
                review_required=not chosen,
                review_reason="" if chosen else "No code",
                unmatched_substantive_concepts=[],
            )
        raise AssertionError(schema)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        openai_api_key="test-key",
        database_url=f"sqlite:///{tmp_path / 'studio.db'}",
        storage_root=tmp_path / "data",
        session_db_path=tmp_path / "sessions.db",
        run_tasks_inline=True,
        autocoder_embeddings="tfidf",
    )


def _upload(client, project: dict, tmp_path: Path) -> None:
    path = tmp_path / "oe.sav"
    frame = pd.DataFrame(
        {"respondent_id": [101, 102, 103, 104, 105, 106], "Q15": _ANSWERS, "S7": [1, 2, 1, 2, 1, 2]}
    )
    pyreadstat.write_sav(
        frame,
        path,
        column_labels={
            "respondent_id": "Respondent",
            "Q15": "Q15: What are the main reasons for the score you gave?",
            "S7": "Gender",
        },
        variable_value_labels={"S7": {1: "Man", 2: "Woman"}},
    )
    with path.open("rb") as handle:
        response = client.post(
            f"/api/projects/{project['id']}/files",
            files={"file": ("oe.sav", handle, "application/octet-stream")},
        )
    assert response.status_code == 201, response.text


def test_autocoder_builds_a_codeframe_and_codes_every_row(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.services.autocode_run._llm_factory", lambda _settings: _FakeLLM)
    project = create_project(client)
    _upload(client, project, tmp_path)
    sent = client.post(
        f"/api/conversations/{project['conversation_id']}/messages",
        json={"content": "Auto-code the open ends in Q15"},
    )
    task = client.get(f"/api/tasks/{sent.json()['task_id']}").json()
    assert task["status"] in {"completed", "completed_with_warnings"}, task
    artifacts = client.get(f"/api/projects/{project['id']}/artifacts").json()
    names = {item["name"]: item for item in artifacts}
    assert "Codeframe Q15 (AutoCoder)" in names
    content = names["Coding Q15 (AutoCoder)"]["latest"]["content"]
    rows = {row["respondent_id"]: row for row in content["assignments"]}
    assert len(rows) == 6
    assert rows["103"]["substantive"] is False
    codes_on = {key: set(row["assigned_code_ids"]) for key, row in rows.items()}
    assert len(codes_on["104"]) == 2
    assert codes_on["101"] and codes_on["101"].isdisjoint(codes_on["102"])
    assert content["autocoder"]["engine"].startswith("Ad Hoc AutoCoder")
    assert content["autocoder_file_id"] and content["export_file_id"]
    assert content["report"]["substantive_n"] == 5
    frame = names["Codeframe Q15 (AutoCoder)"]["latest"]["content"]
    assert {code["label"] for code in frame["codes"]} == {"Too expensive", "Good taste"}
    assert {net["label"] for net in frame["nets"]} >= {"VALUE", "PRODUCT"}


def test_autocoder_asks_which_text_column_and_for_wording() -> None:
    from app.errors import AppError
    from app.services.autocode_run import question_wording, resolve_text_variable

    variables = [
        {"name": "Q15", "label": "Q15: Why?", "is_text": True},
        {"name": "Q16", "label": "", "is_text": True},
        {
            "name": "SYN_PERSONA",
            "label": "Synthetic persona (not a survey answer)",
            "is_text": True,
        },
    ]
    columns = ["Q15", "Q16", "SYN_PERSONA"]
    assert resolve_text_variable({}, "code the open ends in q16", variables, columns) == "Q16"
    with pytest.raises(AppError, match="Which open-end column"):
        resolve_text_variable({}, "code the open ends", variables, columns)
    assert question_wording({}, variables, "Q15") == "Why?"
    with pytest.raises(AppError, match="question wording for Q16"):
        question_wording({}, variables, "Q16")


def test_router_rules_send_open_end_coding_to_the_autocoder() -> None:
    keyword = build_contract(
        task_id="t",
        project_id="p",
        conversation_id="c",
        text='Automatically code Q15, question "Why did you give that score?"',
        variable_names=["Q15"],
        has_dataset=True,
    )
    assert keyword.intent == "autocode_open_ends"
    assert keyword.provided_fields["question_text"] == "Why did you give that score?"
    chosen = build_contract(
        task_id="t",
        project_id="p",
        conversation_id="c",
        text="Use the AutoCoder on the open ends in column Q15",
        variable_names=["Q15"],
        has_dataset=True,
        chosen_intent="code_open_ends",
    )
    assert chosen.intent == "autocode_open_ends"
    assert chosen.provided_fields["response_variable"] == "Q15"
