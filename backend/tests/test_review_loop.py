"""The review loop keeps fixing until nothing is left, and count variables for bases."""

import asyncio

from app.engines.decipher import compile_decipher
from app.schemas.expression import Comparison
from app.schemas.questionnaire import (
    Computation,
    DerivedValue,
    DerivedVariable,
    Option,
    ProgrammingSpec,
    Question,
    Questionnaire,
)
from app.services import program_review
from app.services.program_review import open_problems
from app.services.programming_spec import DerivedPlan, PlanBatch, QuestionPlan, merge_derived


def _survey(**extra) -> Questionnaire:
    return Questionnaire(
        id="t",
        title="Routes",
        questions=[
            Question(
                id="S5",
                type="multi_select",
                text="Which routes do you use?",
                options=[
                    Option(code=1, label="Agency"),
                    Option(code=2, label="In-house"),
                    Option(code=3, label="Self-serve"),
                    Option(code=99, label="None of these", exclusive=True),
                ],
            ),
            Question(
                id="Q9",
                type="single_select",
                text="How do you consolidate routes?",
                programmer_notes=["ASK IF HID_ROUTE_COUNT >= 2"],
                options=[Option(code=1, label="One tool"), Option(code=2, label="Several")],
            ),
        ],
        **extra,
    )


def _count_variable() -> DerivedVariable:
    return DerivedVariable(
        id="HID_ROUTE_COUNT",
        definition="Number of routes selected at S5",
        after="S5",
        compute=Computation(kind="count", sources=["S5"], rows=[1, 2, 3]),
    )


def test_count_variable_counts_the_chosen_rows_and_bases_can_use_it() -> None:
    document = _survey(derived_variables=[_count_variable()])
    q9 = document.questions[1].model_copy(
        update={"display_if": Comparison(op="gte", ref="HID_ROUTE_COUNT", value=2)}
    )
    document = document.model_copy(update={"questions": [document.questions[0], q9]})
    program = compile_decipher(document)
    assert program.validation_status != "failed", program.issues
    assert (
        "HID_ROUTE_COUNT.val = (1 if S5.r1 else 0) + (1 if S5.r2 else 0) + (1 if S5.r3 else 0)"
        in program.xml
    )
    assert 'cond="HID_ROUTE_COUNT.ival &gt;= 2"' in program.xml


def test_a_fix_may_define_a_variable_the_catalog_lacks() -> None:
    document = _survey()
    plan = DerivedPlan(
        id="HID_ROUTE_COUNT",
        definition="Number of routes",
        after="S5",
        compute=Computation(kind="count", sources=["S5"]),
    )
    merged = merge_derived(document, [plan, DerivedPlan(id="S5", values=[])])
    assert [variable.id for variable in merged.derived_variables] == ["HID_ROUTE_COUNT"]
    # An existing variable with values is never replaced by a fix.
    again = merge_derived(
        merged,
        [DerivedPlan(id="HID_ROUTE_COUNT", values=[DerivedValue(code=1, label="x")])],
    )
    assert again.derived_variables[0].compute is not None


def test_logic_set_aside_and_rejected_xml_are_reported_without_the_reviewer() -> None:
    spec = ProgrammingSpec(
        unresolved=[
            "Q9 is shown only when HID_ROUTE_COUNT is at least 2, but HID_ROUTE_COUNT is not a question on this survey.",
            "Quota: 50 per route.",
            "Review: Q9 is shown only when the base holds.",
        ]
    )
    document = _survey()
    document.questions[1] = document.questions[1].model_copy(update={"programming": spec})
    program = compile_decipher(document)
    problems = open_problems(document, program)
    assert list(problems) == ["Q9"]
    assert len(problems["Q9"]) == 1 and "not a question" in problems["Q9"][0]


def _run_loop(monkeypatch, reviews: list[dict], plans) -> tuple:
    calls = {"review": [], "plan": 0}

    async def fake_plan_programming(settings, document, **kwargs):
        return document

    async def fake_review(settings, document, xml, session_id, limit, lessons=None, *, only=None):
        calls["review"].append(only)
        return reviews.pop(0) if reviews else {}

    async def fake_plan_batch(settings, document, group, findings, session_id, limit, lessons):
        calls["plan"] += 1
        return plans(document, group)

    monkeypatch.setattr(program_review, "plan_programming", fake_plan_programming)
    monkeypatch.setattr(program_review, "review", fake_review)
    monkeypatch.setattr(program_review, "plan_batch", fake_plan_batch)
    result = asyncio.run(
        program_review.build_reviewed_program(
            None, _survey(), session_id="s", on_stage=lambda _: None
        )
    )
    return result, calls


def test_the_loop_fixes_then_rechecks_only_what_changed(monkeypatch) -> None:
    def plans(document, group):
        return PlanBatch(
            questions=[
                QuestionPlan(
                    question_id="Q9",
                    display_if=Comparison(op="gte", ref="HID_ROUTE_COUNT", value=2),
                )
            ],
            derived=[
                DerivedPlan(
                    id="HID_ROUTE_COUNT",
                    after="S5",
                    compute=Computation(kind="count", sources=["S5"]),
                )
            ],
        )

    (document, program, fixed), calls = _run_loop(
        monkeypatch, [{"Q9": ["The base HID_ROUTE_COUNT >= 2 is missing."]}, {}], plans
    )
    assert fixed == 1
    assert calls["review"] == [None, {"Q9"}]
    assert document.questions[1].display_if is not None
    assert "HID_ROUTE_COUNT" in program.xml
    assert not (document.questions[1].programming and document.questions[1].programming.unresolved)


def test_the_loop_stops_when_nothing_changes_and_keeps_findings_as_todos(monkeypatch) -> None:
    def plans(document, group):
        return PlanBatch()  # the planner cannot do better

    (document, _, fixed), calls = _run_loop(monkeypatch, [{"Q9": ["Loop over each route."]}], plans)
    assert fixed == 0 and calls["plan"] == 1 and len(calls["review"]) == 1
    assert "Review: Loop over each route." in document.questions[1].programming.unresolved
