"""Bases, piped rows, anchors, and None / Other house rules in the generated Decipher XML."""

import xml.etree.ElementTree as ET

from app.engines.decipher import compile_decipher
from app.schemas.expression import Comparison
from app.schemas.questionnaire import (
    Option,
    ProgrammingSpec,
    Question,
    Questionnaire,
    RowCondition,
)
from app.services.special_options import house_rules


def _root(xml: str) -> ET.Element:
    return ET.fromstring(xml.split("?>", 1)[1])


def _bought() -> Question:
    """A select-all list whose codes are not in list order, as questionnaires often number them."""
    return Question(
        id="Q1",
        type="multi_select",
        text="Which have you bought in the past year?",
        options=[
            Option(code=13, label="Waxed paper"),
            Option(code=17, label="Air fryer filters"),
            Option(code=14, label="Aluminum foil"),
            Option(code=99, label="None of these", exclusive=True, anchor=True),
        ],
    )


def _document(*questions: Question) -> Questionnaire:
    return Questionnaire(id="t", title="Kitchen Study", questions=[_bought(), *questions])


def test_not_equal_on_a_select_all_question_also_needs_an_answer() -> None:
    """An "ASK IF Q1 is not 99" base is false for someone who never answered Q1."""
    follow = Question(
        id="Q2",
        type="text",
        text="Why?",
        display_if=Comparison(op="not_in", ref="Q1", value=[99]),
    )
    root = _root(compile_decipher(_document(follow)).xml)
    assert root.find(".//textarea[@label='Q2']").get("cond") == "(Q1.any and not ((Q1.r99)))"


def test_piped_rows_line_up_with_the_source_by_wording() -> None:
    """Rows piped from Q1 take Q1's row labels, even with other codes and small wording changes."""
    piped = Question(
        id="Q3",
        type="multi_select",
        text="Which do you buy online?",
        options=[
            Option(code=1, label="Waxed Paper"),
            Option(code=2, label="Air-fryer filters."),
            Option(code=3, label="Aluminum foil"),
        ],
        programming=ProgrammingSpec(row_condition=RowCondition(source="Q1")),
    )
    grid = Question(
        id="Q4",
        type="grid",
        text="How often do you buy these?",
        matrix_items=["Aluminium foil", "Waxed paper", "Air fryer filters"],
        options=[Option(code=1, label="Rarely"), Option(code=2, label="Often")],
        programming=ProgrammingSpec(row_condition=RowCondition(source="Q1")),
    )
    program = compile_decipher(_document(piped, grid))
    root = _root(program.xml)
    q3 = root.find(".//checkbox[@label='Q3']")
    assert [row.get("label") for row in q3.findall("row")] == ["r13", "r17", "r14"]
    assert q3.get("rowCond") == "Q1[row]"
    # The question is skipped when nothing was bought, as programmers write it.
    assert q3.get("cond") == "Q1.any"
    q4 = root.find(".//radio[@label='Q4']")
    assert [row.get("label") for row in q4.findall("row")] == ["r14", "r13", "r17"]
    assert not any("has no row worded like" in warning for warning in program.warnings)


def test_piped_row_missing_from_the_source_is_reported() -> None:
    """A piped row the source does not have cannot be shown by rowCond; the programmer is told."""
    piped = Question(
        id="Q3",
        type="multi_select",
        text="Which do you buy online?",
        options=[Option(code=13, label="Waxed paper"), Option(code=20, label="Paper towels")],
        programming=ProgrammingSpec(row_condition=RowCondition(source="Q1")),
    )
    program = compile_decipher(_document(piped))
    assert any("Q3 shows rows picked at Q1" in w and "Paper towels" in w for w in program.warnings)


def test_piped_base_joins_a_written_base() -> None:
    """A written base and the piped rows' base are both kept."""
    piped = Question(
        id="Q3",
        type="multi_select",
        text="Which do you buy online?",
        display_if=Comparison(op="eq", ref="Q1", value=13),
        options=[Option(code=13, label="Waxed paper"), Option(code=14, label="Aluminum foil")],
        programming=ProgrammingSpec(row_condition=RowCondition(source="Q1")),
    )
    root = _root(compile_decipher(_document(piped)).xml)
    assert root.find(".//checkbox[@label='Q3']").get("cond") == "(Q1.r13) and Q1.any"


def test_anchored_rows_stay_put_in_an_alphabetical_list() -> None:
    """A "LIST ALPHABETICALLY" list with None anchored: None keeps its place at the bottom."""
    sorted_list = Question(
        id="Q5",
        type="multi_select",
        text="Which brands do you know?",
        options=[
            Option(code=1, label="Ziploc"),
            Option(code=2, label="Glad"),
            Option(code=99, label="None of these", exclusive=True, anchor=True),
        ],
        programming=ProgrammingSpec(sort_alphabetically=True),
    )
    root = _root(compile_decipher(_document(sorted_list)).xml)
    q5 = root.find(".//checkbox[@label='Q5']")
    assert q5.get("sortRows") == "asc,survey"
    assert q5.find("row[@label='r99']").get("randomize") == "0"
    assert q5.find("row[@label='r1']").get("randomize") is None


def test_house_rules_for_none_dont_know_and_other() -> None:
    """None and Don't know become exclusive and anchored; Other (specify) gets a box and is not exclusive."""
    question = Question(
        id="Q6",
        type="multi_select",
        text="Which apply?",
        exclusive_codes=[98],
        options=[
            Option(code=1, label="Tablet"),
            Option(code=98, label="Other, (please specify):", exclusive=True, anchor=True),
            Option(code=97, label="Don't know"),
            Option(code=99, label="Prefer not to answer"),
        ],
    )
    fixed = house_rules(question)
    by_code = {option.code: option for option in fixed.options}
    assert by_code[98].open_text and not by_code[98].exclusive
    assert by_code[97].exclusive and by_code[97].anchor
    assert by_code[99].exclusive and by_code[99].anchor
    assert not by_code[1].exclusive
    assert fixed.exclusive_codes == [97, 99]


def test_house_rules_follow_the_notes() -> None:
    """Notes that make Other exclusive win; a single-choice question only gets the write-in box."""
    exclusive_other = Question(
        id="Q7",
        type="multi_select",
        text="Which apply?",
        programmer_notes=["Make Other (98) exclusive."],
        options=[
            Option(code=1, label="Tablet"),
            Option(code=98, label="Other (specify)", exclusive=True),
        ],
    )
    assert house_rules(exclusive_other).options[1].exclusive
    single = Question(
        id="S1",
        type="single_select",
        text="Do you identify as...?",
        options=[
            Option(code=1, label="Male"),
            Option(code=4, label="Prefer to self-describe (other)"),
        ],
    )
    fixed = house_rules(single)
    assert fixed.options[1].open_text and not fixed.options[1].exclusive


def test_settle_keeps_a_derived_variables_codes_when_its_conditions_fail() -> None:
    """A brand assignment that tests undefined flags keeps its codes, so questions using it still build."""
    from app.schemas.questionnaire import DerivedValue, DerivedVariable
    from app.services.programming_spec import settle, spec_issues

    document = Questionnaire(
        id="t",
        title="Brand Study",
        questions=[
            Question(
                id="Q1",
                type="single_select",
                text="Do you know it?",
                display_if=Comparison(op="eq", ref="HID_BRAND", value=2),
                options=[Option(code=1, label="Yes"), Option(code=2, label="No")],
            )
        ],
        derived_variables=[
            DerivedVariable(
                id="HID_BRAND",
                definition="Assign one eligible sub-brand.",
                values=[
                    DerivedValue(
                        code=code,
                        label=label,
                        when=Comparison(op="eq", ref=f"HID_ELIG_{code}", value=1),
                    )
                    for code, label in ((1, "Alexa"), (2, "Echo"))
                ],
            )
        ],
    )
    assert "HID_BRAND" in spec_issues(document)
    settled = settle(document)
    brand = settled.derived_variables[0]
    assert [value.code for value in brand.values] == [1, 2]
    assert all(value.when is None for value in brand.values) and brand.unresolved
    program = compile_decipher(settled)
    assert program.validation_status != "failed", program.issues
    assert _root(program.xml).find(".//radio[@label='Q1']").get("cond") == "HID_BRAND.r2"


def test_number_entry_rows_are_not_write_ins() -> None:
    """A "___%" entry row on a number question is not a text box; an Other row keeps one."""
    question = Question(
        id="N1",
        type="allocation",
        text="Share of budget?",
        options=[
            Option(code=1, label="Streaming: ___%", open_text=True),
            Option(code=2, label="Other (specify): ___%", open_text=True),
        ],
    )
    fixed = house_rules(question)
    assert [option.open_text for option in fixed.options] == [False, True]


def test_derived_variables_computed_after_other_derived_variables_are_emitted() -> None:
    """HID_BRAND after Q1 and HID_BRAND_LABEL after HID_BRAND both reach the XML, in that order."""
    from app.schemas.questionnaire import DerivedValue, DerivedVariable

    def variable(name: str, after: str) -> DerivedVariable:
        return DerivedVariable(
            id=name,
            definition="Assigned.",
            after=after,
            values=[DerivedValue(code=1, label="Alexa"), DerivedValue(code=2, label="Echo")],
        )

    document = _document(
        Question(
            id="Q2",
            type="text",
            text="Why?",
            display_if=Comparison(op="eq", ref="HID_BRAND_LABEL", value=2),
        )
    ).model_copy(
        update={
            "derived_variables": [
                variable("HID_BRAND_LABEL", "HID_BRAND"),
                variable("HID_BRAND", "Q1"),
            ]
        }
    )
    program = compile_decipher(document)
    assert program.validation_status != "failed", program.issues
    labels = [node.get("label") for node in _root(program.xml).iter() if node.get("label")]
    assert labels.index("Q1") < labels.index("HID_BRAND") < labels.index("HID_BRAND_LABEL")


def test_dont_know_columns_are_named_by_their_code() -> None:
    """A 6-to-1 scale with Other 96 and Don't know 97 numbers only the scale points."""
    from app.engines.decipher_expr import col_labels

    descending = [Option(code=c, label=f"Point {c}") for c in (6, 5, 4, 3, 2, 1)]
    labels = col_labels([*descending, Option(code=97, label="Don't know")])
    assert labels["6"] == ("c1", "6") and labels["1"] == ("c6", "1")
    assert labels["97"] == ("c97", "97")
    ascending = col_labels(
        [Option(code=98, label="Not familiar")] + [Option(code=c, label=str(c)) for c in (1, 2, 3)]
    )
    assert ascending == {
        "98": ("c98", "98"),
        "1": ("c1", None),
        "2": ("c2", None),
        "3": ("c3", None),
    }
    after_five = col_labels(
        [Option(code=c, label=str(c)) for c in (5, 4, 3, 2, 1)]
        + [Option(code=9, label="Don't know")]
    )
    assert after_five["9"] == ("c9", "9") and after_five["5"] == ("c1", "5")


def test_list_named_in_the_notes_is_copied_before_the_questions_own_extras() -> None:
    """ "[Same list as Q1]" with only None and Don't know of its own gets Q1's list first."""
    from app.services.programming_spec import QuestionPlan, _apply

    follow = Question(
        id="Q8",
        type="multi_select",
        text="Which of these have specialists?",
        programmer_notes=["[PIPE IN ALL items from Q1]"],
        options=[Option(code=98, label="None of these"), Option(code=97, label="Don't know")],
    )
    planned = _apply(_document(follow), [QuestionPlan(question_id="Q8")])
    q8 = next(question for question in planned.questions if question.id == "Q8")
    assert [option.code for option in q8.options] == [13, 17, 14, 98, 97]
    assert not q8.options[0].exclusive and q8.options[3].exclusive


def test_list_copied_from_a_grid_takes_its_rows() -> None:
    """A list piped from a grid's rows gets those rows, numbered by position, not its scale."""
    from app.services.programming_spec import QuestionPlan, _apply

    grid = Question(
        id="G1",
        type="grid",
        text="How do you buy?",
        matrix_items=["Direct", "Agency", "Marketplace"],
        options=[Option(code=1, label="Never"), Option(code=3, label="Currently")],
    )
    follow = Question(
        id="Q9",
        type="multi_select",
        text="Which do you use most?",
        options=[Option(code=98, label="None of these")],
    )
    planned = _apply(_document(grid, follow), [QuestionPlan(question_id="Q9", list_from="G1")])
    q9 = next(question for question in planned.questions if question.id == "Q9")
    assert [(o.code, o.label) for o in q9.options] == [
        (1, "Direct"),
        (2, "Agency"),
        (3, "Marketplace"),
        (98, "None of these"),
    ]


def test_grid_with_repeated_codes_still_builds() -> None:
    """Either/or pairs coded 1, 2 each get unique columns and a warning instead of failing."""
    pairs = Question(
        id="A14",
        type="grid",
        text="Which is closer to your view?",
        matrix_items=["Statement set"],
        options=[
            Option(code=1, label="Left view A"),
            Option(code=2, label="Right view A"),
            Option(code=1, label="Left view B"),
            Option(code=2, label="Right view B"),
        ],
    )
    program = compile_decipher(_document(pairs))
    assert program.validation_status != "failed", program.issues
    grid = _root(program.xml).find(".//radio[@label='A14']")
    assert [col.get("label") for col in grid.findall("col")] == ["c1", "c2", "c3", "c4"]
    assert any("A14 repeats answer codes" in warning for warning in program.warnings)
