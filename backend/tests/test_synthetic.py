"""Synthetic respondents follow the survey flow, meet quotas, and land as an SPSS dataset."""

import asyncio
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from app.agents.intent import build_contract, product_lock
from app.config import Settings
from app.engines.decipher import compile_decipher
from app.engines.synthetic_sim import check_quotas, simulate
from app.engines.synthetic_spss import build_frame, check_file, write_sav
from app.engines.synthetic_survey import parse_survey
from app.main import create_app
from app.repositories.records import ArtifactRepository, DatasetRepository, ProjectRepository
from app.schemas.expression import Comparison
from app.schemas.questionnaire import Option, Question, Questionnaire
from app.schemas.synthetic import (
    GridRow,
    Persona,
    PersonaAnswers,
    QuestionProfile,
    QuotaTarget,
    Weight,
)
from app.services.execute import load_frame
from app.services.synthetic_run import run_synthetic
from tests.conftest import create_project


def _questionnaire() -> Questionnaire:
    """A short survey with a screener, a quota question, routing, and every answer type."""
    brands = [Option(code=index, label=f"Brand {index}") for index in range(1, 6)]
    return Questionnaire(
        id="q-syn",
        title="Synthetic check",
        questions=[
            Question(
                id="S1",
                type="screener",
                text="Do you drink coffee at home?",
                options=[Option(code=1, label="Yes"), Option(code=2, label="No", terminate=True)],
            ),
            Question(
                id="S2",
                type="single_select",
                text="Gender",
                options=[Option(code=1, label="Woman"), Option(code=2, label="Man")],
            ),
            Question(id="S3", type="numeric", text="How old are you?"),
            Question(
                id="Q1",
                type="multi_select",
                text="Which brands have you bought?",
                options=[*brands[:3], Option(code=99, label="None of these", exclusive=True)],
            ),
            Question(
                id="Q2",
                type="text",
                text="Why did you buy Brand 1?",
                display_if=Comparison(op="in", ref="Q1", value=[1]),
            ),
            Question(
                id="Q3",
                type="grid",
                text="Rate each brand",
                matrix_items=["Brand 1", "Brand 2"],
                options=[Option(code=1, label="Poor"), Option(code=2, label="Good")],
            ),
            Question(
                id="Q4",
                type="rank",
                text="Rank your top three brands",
                options=brands,
            ),
            Question(
                id="Q5",
                type="allocation",
                text="Allocate 100 points",
                options=[Option(code=1, label="Taste"), Option(code=2, label="Price")],
            ),
        ],
    )


def _specs():
    """Compile the survey and read it back as specs."""
    document = _questionnaire()
    program = compile_decipher(document)
    items = [item.model_dump() for item in program.items]
    questions = [question.model_dump() for question in document.questions]
    return parse_survey(program.xml, items, questions)


def test_respondents_follow_routing_quotas_and_rules() -> None:
    """Terminates are replaced, quotas are exact, hidden questions stay blank, ranks are unique."""
    specs = _specs()
    quotas, dropped = check_quotas(
        specs,
        [
            QuotaTarget(question="S2", code="1", share=0.5),
            QuotaTarget(question="S2", code="Man", share=0.5),
            QuotaTarget(question="S3", lower=18, upper=34, share=0.5),
            QuotaTarget(question="S3", lower=35, upper=65, share=0.5),
            QuotaTarget(question="ZZ", code="1", share=1.0),
        ],
    )
    assert len(quotas) == 4
    assert dropped and "ZZ" in dropped[0]
    profiles = {
        "S1": QuestionProfile(
            label="S1",
            personas=[
                PersonaAnswers(
                    persona="Fan",
                    weights=[Weight(code="1", weight=0.7), Weight(code="2", weight=0.3)],
                )
            ],
        ),
        "Q3": QuestionProfile(
            label="Q3",
            personas=[
                PersonaAnswers(
                    persona="Fan",
                    grid=[GridRow(row="1", weights=[Weight(code="2", weight=1.0)])],
                )
            ],
        ),
    }
    simulation = simulate(specs, [Persona(name="Fan", share=1.0)], quotas, profiles, 120, seed=11)
    frame, meta = build_frame(specs, simulation)
    payload = write_sav(frame, meta)
    checks, counts = check_file(payload, frame, specs, simulation, 120)
    assert all(check.status == "passed" for check in checks), [c.details for c in checks]
    assert simulation.terminated > 0
    assert set(frame["S1"]) == {1}
    assert {(item.label, item.target, item.achieved) for item in counts} == {
        ("Woman", 60, 60),
        ("Man", 60, 60),
        ("18-34", 60, 60),
        ("35-65", 60, 60),
    }
    assert set(frame["Q3r1"]) == {2}
    picked_brand_1 = frame["Q1r1"] == 1
    assert (frame.loc[~picked_brand_1, "Q2"] == "").all()
    assert (frame.loc[picked_brand_1, "Q2"] != "").all()
    none_of_these = frame["Q1r99"] == 1
    assert (frame.loc[none_of_these, ["Q1r1", "Q1r2", "Q1r3"]].sum(axis=1) == 0).all()
    ranks = frame[[f"Q4r{code}" for code in range(1, 6)]]
    assert (ranks.notna().sum(axis=1) == 3).all()
    assert (frame["Q5r1"] + frame["Q5r2"] == 100).all()
    assert meta["values"]["S2"] == {1: "Woman", 2: "Man"}


def test_same_seed_gives_the_same_file() -> None:
    """The stored seed regenerates the same respondents."""
    specs = _specs()
    first = build_frame(specs, simulate(specs, [], [], {}, 30, seed=5))[0]
    second = build_frame(specs, simulate(specs, [], [], {}, 30, seed=5))[0]
    pd.testing.assert_frame_equal(first, second)


def test_synthetic_requests_route_to_the_generator() -> None:
    """Mentioning Decipher in a synthetic-data request does not start programming."""
    text = "Generate 300 synthetic respondents from the Decipher survey"
    assert product_lock(text) == "generate_synthetic"
    contract = build_contract(
        task_id="t",
        project_id="p",
        conversation_id="c",
        text=text,
        variable_names=[],
        has_dataset=False,
    )
    assert contract.intent == "generate_synthetic"
    assert contract.specialist == "synthetic"
    assert product_lock("Program the survey in Decipher") == "program_decipher"


def test_run_publishes_an_active_spss_dataset(tmp_path: Path) -> None:
    """Without a model key the run still writes uniform data, an SPSS file, and the active dataset."""
    settings = Settings(
        openai_api_key="",
        anthropic_api_key="",
        database_url=f"sqlite:///{(tmp_path / 'studio.db').as_posix()}",
        storage_root=tmp_path / "storage",
        session_db_path=tmp_path / "sessions.db",
        run_tasks_inline=True,
        cors_origins="http://localhost:5173",
        decipher_api_base="",
        decipher_api_key="",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        project = create_project(client)
        conversation = client.get(f"/api/projects/{project['id']}/conversations").json()[0]["id"]
    document = _questionnaire()
    program = compile_decipher(document)
    db = app.state.session_factory()
    try:
        repo = ArtifactRepository(db)
        repo.create(
            project_id=project["id"],
            artifact_type="questionnaire",
            name="Q",
            content=document.model_dump(mode="json"),
            content_schema="questionnaire/1",
            created_by="test",
            validation_status="passed",
        )
        repo.create(
            project_id=project["id"],
            artifact_type="decipher_survey",
            name="Decipher",
            content=program.model_dump(mode="json"),
            content_schema="decipher/1",
            created_by="test",
            validation_status="passed",
        )
        db.commit()
        outcome = asyncio.run(
            run_synthetic(
                db,
                app.state.storage,
                settings,
                project["id"],
                conversation,
                "Generate 80 synthetic respondents",
            )
        )
        db.commit()
        saved = ArtifactRepository(db).latest_of_type(project["id"], "synthetic_data")
        active = ProjectRepository(db).get(project["id"]).active_dataset_id
        dataset = DatasetRepository(db).get(active)
        frame = load_frame(app.state.storage, dataset)
    finally:
        db.close()
    assert outcome["status"] == "completed"
    assert "80 synthetic completes" in outcome["summary"]
    assert saved.content["dataset_active"] is True
    assert saved.content["answer_source"] == "uniform"
    assert saved.content["export_file_id"]
    assert len(frame) == 80
    assert {"S1", "S2", "Q1r99", "Q4r1", "SYN_PERSONA"} <= set(frame.columns)
    names = {item["name"] for item in dataset.variables}
    assert "Q3r1" in names


def test_shared_trait_links_answers_and_personas_fit_quota_cells() -> None:
    """Rows that load on one trait correlate, and an older persona fills the older age cell."""
    from app.schemas.synthetic import Loading, TraitLevel

    specs = _specs()
    affinity = [TraitLevel(trait="Affinity", level=0.0)]
    people = [
        Persona(name="Young", share=0.5, traits=affinity),
        Persona(name="Older", share=0.5, traits=affinity),
    ]
    profiles = {
        "S3": QuestionProfile(
            label="S3",
            personas=[
                PersonaAnswers(persona="Young", minimum=18, maximum=34, typical=26),
                PersonaAnswers(persona="Older", minimum=50, maximum=65, typical=57),
            ],
        ),
        "Q3": QuestionProfile(
            label="Q3",
            loadings=[
                Loading(trait="Affinity", target="1", effect=1.5),
                Loading(trait="Affinity", target="2", effect=1.5),
            ],
        ),
    }
    quotas, _ = check_quotas(
        specs,
        [
            QuotaTarget(question="S3", lower=18, upper=34, share=0.5),
            QuotaTarget(question="S3", lower=50, upper=65, share=0.5),
        ],
    )
    simulation = simulate(specs, people, quotas, profiles, 400, seed=3)
    frame, _ = build_frame(specs, simulation)
    assert frame["Q3r1"].corr(frame["Q3r2"]) > 0.3
    older = frame[frame["S3"] >= 50]
    assert (older["SYN_PERSONA"] == "Older").mean() > 0.9
    assert abs((frame["SYN_PERSONA"] == "Older").mean() - 0.5) < 0.1
