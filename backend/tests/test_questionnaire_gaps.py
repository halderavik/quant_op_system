"""Computed values, section rotation, alphabetical lists, and image placeholders in the XML."""

import xml.etree.ElementTree as ET

from app.engines.decipher import compile_decipher, range_midpoint
from app.engines.decipher_markup import image_file
from app.schemas.questionnaire import (
    BlockRotation,
    Computation,
    DerivedVariable,
    Option,
    ProgrammingSpec,
    Question,
    Questionnaire,
)


def _single(qid: str, labels: list[str], **extra: object) -> Question:
    options = [Option(code=i, label=label) for i, label in enumerate(labels, start=1)]
    return Question(id=qid, type="single_select", text=f"{qid} text", options=options, **extra)


def _survey(questions: list[Question], **extra: object) -> Questionnaire:
    return Questionnaire(id="q", title="Gaps", questions=questions, **extra)


def _root(document: Questionnaire) -> ET.Element:
    program = compile_decipher(document)
    assert program.validation_status != "failed", program.issues
    return ET.fromstring(program.xml.split("\n", 1)[1])


def test_midpoints_of_answer_ranges() -> None:
    assert range_midpoint("25-34") == 29.5
    assert range_midpoint("$50,000 to $74,999") == 62499.5
    assert range_midpoint("Under $25K") == 12500
    assert range_midpoint("65 or older") == 65
    assert range_midpoint("Prefer not to say") is None


def test_a_midpoint_variable_is_computed_from_the_chosen_range() -> None:
    document = _survey(
        [_single("S2", ["18-24", "25-34", "Prefer not to say"])],
        derived_variables=[
            DerivedVariable(
                id="HV_AGE",
                label="Age midpoint",
                definition="Midpoint of S2",
                after="S2",
                compute=Computation(kind="midpoint", sources=["S2"]),
            )
        ],
    )
    root = _root(document)
    node = root.find(".//float[@label='HV_AGE']")
    assert node is not None
    code = "\n".join(e.text or "" for e in root.iter("exec"))
    assert "(S2.r1, 21)" in code and "(S2.r2, 29.5)" in code and "S2.r3" not in code
    assert "HV_AGE.val = middle" in code


def test_a_sum_adds_the_chosen_rows_of_a_numeric_list() -> None:
    numeric = Question(
        id="Q5",
        type="numeric",
        text="Hours",
        options=[Option(code=1, label="Weekdays"), Option(code=2, label="Weekends")],
    )
    document = _survey(
        [numeric, Question(id="Q6", type="numeric", text="Other hours")],
        derived_variables=[
            DerivedVariable(
                id="HV_TOTAL",
                definition="Q5 + Q6",
                after="Q6",
                compute=Computation(kind="sum", sources=["Q5", "Q6"]),
            )
        ],
    )
    code = "\n".join(e.text or "" for e in _root(document).iter("exec"))
    assert "HV_TOTAL.val = (Q5.r1.val or 0) + (Q5.r2.val or 0) + (Q6.val or 0)" in code


def test_sections_are_wrapped_in_randomized_blocks() -> None:
    questions = [_single(qid, ["Yes", "No"]) for qid in ["S1", "A1", "A2", "B1", "B2", "Z1"]]
    document = _survey(
        questions,
        rotations=[BlockRotation(groups=[["A1", "A2"], ["B1", "B2"]], note="Rotate A and B")],
    )
    root = _root(document)
    outer = root.find(".//block[@randomizeChildren='1']")
    assert outer is not None
    inner = outer.findall("block")
    assert [b.get("randomize") for b in inner] == ["1", "1"]
    assert [[q.get("label") for q in b.findall("radio")] for b in inner] == [
        ["A1", "A2"],
        ["B1", "B2"],
    ]
    assert root.find("radio[@label='Z1']") is not None


def test_a_rotation_with_gaps_is_left_to_the_programmer() -> None:
    questions = [_single(qid, ["Yes", "No"]) for qid in ["A1", "X1", "B1"]]
    program = compile_decipher(
        _survey(questions, rotations=[BlockRotation(groups=[["A1"], ["B1"]])])
    )
    assert "randomizeChildren" not in program.xml
    assert any("Section rotation not programmed" in w for w in program.warnings)


def test_alphabetical_lists_and_images() -> None:
    question = _single(
        "Q1",
        ["Zebra", "Apple"],
        programming=ProgrammingSpec(sort_alphabetically=True, images=["Concept_A.png", "Ad still"]),
    )
    program = compile_decipher(_survey([question]))
    node = ET.fromstring(program.xml.split("\n", 1)[1]).find(".//radio[@label='Q1']")
    assert node.get("sortRows") == "asc,survey"
    sources = [img.get("src") for img in node.find("title").iter("img")]
    assert sources == ["[rel Concept_A.png]", "[rel Ad_still.png]"]
    assert any("upload Ad_still.png" in w for w in program.warnings)
    assert image_file("photo.JPG") == "photo.JPG"


def test_rotation_notes_are_planned_once_for_the_survey(monkeypatch) -> None:
    """Only a survey with a rotation note asks the model, and its answer is kept."""
    import asyncio

    from app.config import Settings
    from app.services import programming_spec
    from app.services.programming_spec import PlanBatch

    prompts: list[str] = []

    async def fake_run(settings, prompt, session_id):
        prompts.append(prompt)
        return PlanBatch(rotations=[BlockRotation(groups=[["A1"], ["B1"]], note="ROTATE A/B")])

    monkeypatch.setattr(programming_spec, "_run", fake_run)
    plain = _survey([_single("A1", ["Yes", "No"]), _single("B1", ["Yes", "No"])])
    noted = plain.model_copy(update={"programming_notes": ["ROTATE SECTIONS A AND B"]})
    settings = Settings(openai_api_key="sk-x", anthropic_api_key="")

    def plan(document: Questionnaire) -> Questionnaire:
        return asyncio.run(
            programming_spec._plan_rotations(
                settings, document, "s", asyncio.Semaphore(1), lambda _: None
            )
        )

    assert plan(plain).rotations == [] and prompts == []
    assert plan(noted).rotations[0].groups == [["A1"], ["B1"]]
    assert "ROTATE SECTIONS A AND B" in prompts[0]


def test_same_order_as_also_shuffles_rows():
    """Decipher follows shuffleBy only on a question whose rows shuffle."""
    brands = [Option(code=1, label="Amazon"), Option(code=2, label="Staples")]
    first = Question(
        id="CAT2", type="single_select", text="Pick one", options=brands, randomize_options=True
    )
    second = Question(
        id="CAT4",
        type="single_select",
        text="Pick again",
        options=brands,
        programming=ProgrammingSpec(same_order_as="CAT2"),
    )
    xml = compile_decipher(Questionnaire(id="q", title="t", questions=[first, second])).xml
    node = ET.fromstring(xml).find(".//radio[@label='CAT4']")
    assert node.get("shuffleBy") == "CAT2"
    assert node.get("shuffle") == "rows"


def test_same_order_as_a_fixed_list_does_not_shuffle():
    """Following a question that is not shuffled keeps the rows in order."""
    brands = [Option(code=1, label="Amazon"), Option(code=2, label="Staples")]
    first = Question(id="S14", type="single_select", text="Pick one", options=brands)
    second = Question(
        id="S15",
        type="single_select",
        text="Pick again",
        options=brands,
        programming=ProgrammingSpec(same_order_as="S14"),
    )
    xml = compile_decipher(Questionnaire(id="q", title="t", questions=[first, second])).xml
    assert ET.fromstring(xml).find(".//radio[@label='S15']").get("shuffle") is None


def test_number_with_only_a_no_answer_box_does_not_shuffle():
    """An age entry marked random by mistake gets no row shuffle."""
    age = Question(
        id="S1",
        type="numeric",
        text="How old are you?",
        options=[Option(code=99, label="Prefer not to answer")],
        randomize_options=True,
        programming=ProgrammingSpec(noanswer_codes=[99], min_value=1, max_value=115),
    )
    xml = compile_decipher(Questionnaire(id="q", title="t", questions=[age])).xml
    assert ET.fromstring(xml).find(".//number[@label='S1']").get("shuffle") is None
