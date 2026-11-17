"""Programming logic from written instructions, house-style Decipher XML, and the review helpers."""

import xml.etree.ElementTree as ET

from app.engines.decipher import compile_decipher
from app.engines.decipher_compare import compare_surveys
from app.schemas.expression import BoolExpr, Comparison
from app.schemas.questionnaire import (
    DerivedValue,
    DerivedVariable,
    Module,
    Option,
    ProgrammingSpec,
    Question,
    Questionnaire,
    RowCondition,
)
from app.services.program_review import _as_todos, question_snippets
from app.services.programming_spec import inherit_piped_lists, settle, spec_issues

NS = {"ss": "http://decipherinc.com/ss"}


def _survey() -> Questionnaire:
    """A screener with flagged terminates, piped rows, numbers, an open end, and a segment."""
    return Questionnaire(
        id="t",
        title="Reading Study",
        terminate_after="S3",
        modules=[Module(id="M1", title="SCREENER", question_ids=["S1", "S2", "S3"])],
        questions=[
            Question(
                id="S1",
                type="multi_select",
                text="Which have you done?",
                randomize_options=True,
                options=[
                    Option(code=1, label="Read a book"),
                    Option(code=2, label="Listened to a podcast"),
                    Option(code=99, label="None of the above", exclusive=True, anchor=True),
                ],
                programmer_notes=["If punch 1 not selected, TERMINATE."],
                programming=ProgrammingSpec(terminate_when=Comparison(op="ne", ref="S1", value=1)),
            ),
            Question(
                id="S2",
                type="numeric",
                text="How many times in the past 6 months?",
                options=[
                    Option(code=1, label="Read a book"),
                    Option(code=2, label="Listened to a podcast"),
                ],
                programmer_notes=["Show items they selected at S1. Allow 0-999."],
                programming=ProgrammingSpec(
                    min_value=0, max_value=999, row_condition=RowCondition(source="S1")
                ),
            ),
            Question(
                id="S3",
                type="numeric",
                text="What is your age?",
                options=[Option(code=99, label="Prefer not to answer", terminate=True)],
                programming=ProgrammingSpec(
                    min_value=1,
                    max_value=120,
                    noanswer_codes=[99],
                    terminate_when=Comparison(op="lt", ref="S3", value=18),
                    terminate_immediately=True,
                ),
            ),
            Question(
                id="Q1",
                type="grid",
                text="How likely are you to...",
                matrix_items=["Buy a print book", "Buy an eBook"],
                options=[Option(code=c, label=str(c)) for c in (5, 4, 3, 2, 1)],
                programming=ProgrammingSpec(keep_together=[]),
            ),
            Question(
                id="Q2",
                type="grid",
                text="Rate from 0 to 10",
                matrix_items=["Brand A"],
                options=[Option(code=c, label=str(c)) for c in range(0, 11)],
                display_if=Comparison(op="eq", ref="HV_READER", value=1),
            ),
            Question(
                id="Q3",
                type="text",
                text="Name a book you enjoyed.",
                programming=ProgrammingSpec(single_line=True, min_chars=3),
            ),
            Question(
                id="Q4",
                type="single_select",
                text="Hidden question",
                options=[Option(code=1, label="Yes"), Option(code=2, label="No")],
                programming=ProgrammingSpec(hidden=True, unresolved=["Quota on Q4 not programmed"]),
            ),
        ],
        derived_variables=[
            DerivedVariable(
                id="HV_READER",
                label="Reader type",
                definition="Reader: read at least one book at S2.",
                after="S2",
                values=[
                    DerivedValue(
                        code=1, label="Reader", when=Comparison(op="gte", ref="S2", row=1, value=1)
                    ),
                    DerivedValue(
                        code=2,
                        label="Non-reader",
                        when=Comparison(op="lt", ref="S2", row=1, value=1),
                        terminate=True,
                    ),
                ],
            )
        ],
    )


def _root(xml: str) -> ET.Element:
    return ET.fromstring(xml.split("?>", 1)[1])


def test_house_style_xml_carries_the_programming() -> None:
    """Codes name rows, ranges and piping are set, segments are computed, and flags fire after the screener."""
    program = compile_decipher(_survey())
    assert program.validation_status != "failed", program.issues
    assert 'xmlns:ss="http://decipherinc.com/ss"' in program.xml
    root = _root(program.xml)
    assert root.get("{http://decipherinc.com/ss}disableBackButton") == "1"
    s1 = root.find(".//checkbox[@label='S1']")
    assert [row.get("label") for row in s1.findall("row")] == ["r1", "r2", "r99"]
    s2 = root.find(".//number[@label='S2']")
    assert s2.get("rowCond") == "S1[row]" and s2.get("verify") == "range(0,999)"
    s3 = root.find(".//number[@label='S3']")
    assert s3.find("noanswer").get("label") == "r99" and s3.get("verify") == "range(1,120)"
    q1 = root.find(".//radio[@label='Q1']")
    assert [(c.get("label"), c.get("value")) for c in q1.findall("col")][:2] == [
        ("c1", "5"),
        ("c2", "4"),
    ]
    q2 = root.find(".//radio[@label='Q2']")
    assert q2.find("col").get("label") == "c0" and q2.get("cond") == "HV_READER.r1"
    q3 = root.find(".//text[@label='Q3']")
    assert "lt 3" in q3.find("validate").text
    q4 = root.find(".//radio[@label='Q4']")
    assert q4.get("cond") == "0" and "PROGRAMMER TODO: Quota on Q4" in program.xml
    reader = root.find(".//radio[@label='HV_READER']")
    assert reader.get("where") == "execute,survey,report"
    assert "S2.r1.ival &gt;= 1" in program.xml
    terms = [term.get("label") for term in root.iter("term")]
    labels = [element.get("label") for element in root.iter() if element.get("label")]
    # The S1 flag waits for the end of the screener (after S3); the S3 age check is immediate.
    assert labels.index("Term_S1") > labels.index("S3")
    assert "Term_S3" in terms
    assert "group_rows" not in program.xml
    # A derived group the file marks TERMINATE screens out, held with the screener flags.
    assert "Term_HV_READER_r2" in terms


def test_logic_checks_flag_bad_references_and_unprogrammed_bases() -> None:
    """Unknown codes and forgotten bases are problems; settle turns what is left into to-dos."""
    document = _survey()
    document.questions[5] = document.questions[5].model_copy(
        update={"programmer_notes": ["Ask if S1=1."], "display_if": None}
    )
    document.questions[2] = document.questions[2].model_copy(
        update={
            "programming": ProgrammingSpec(
                terminate_when=BoolExpr(op="and", args=[Comparison(op="eq", ref="S1", value=7)])
            )
        }
    )
    problems = spec_issues(document)
    assert any("no code 7" in message for message in problems["S3"])
    assert any("but no show-if" in message for message in problems["Q3"])
    settled = settle(document)
    s3 = next(q for q in settled.questions if q.id == "S3")
    assert s3.programming.terminate_when is None and s3.programming.unresolved
    assert "S3" not in spec_issues(settled)


def test_piped_list_is_copied_from_its_source() -> None:
    """'Display genres selected at S1' with no list gets S1's options, without the exclusive one."""
    document = _survey()
    document.questions.append(
        Question(
            id="Q5",
            type="single_select",
            text="Which is your favourite?",
            programming=ProgrammingSpec(row_condition=RowCondition(source="S1")),
        )
    )
    filled = inherit_piped_lists(document)
    assert [o.code for o in filled.questions[-1].options] == [1, 2]


def test_duplicate_codes_still_give_unique_rows() -> None:
    """A questionnaire that repeats a code by mistake still programs, with a warning."""
    document = Questionnaire(
        id="d",
        title="Dup",
        questions=[
            Question(
                id="D8",
                type="single_select",
                text="Affiliation?",
                options=[
                    Option(code=98, label="No affiliation"),
                    Option(code=98, label="Prefer not to answer"),
                ],
            )
        ],
    )
    program = compile_decipher(document)
    assert program.validation_status != "failed", program.issues
    assert any("code 98 more than once" in warning for warning in program.warnings)


def test_review_helpers_and_comparison() -> None:
    """Snippets include the terms after a question; findings become to-dos; a survey scores 1.0 against itself."""
    program = compile_decipher(_survey())
    snippets = question_snippets(program.xml)
    assert "Term_S3" in snippets["S3"]
    flagged = _as_todos(_survey(), {"Q3": ["minimum length should be 5"]})
    assert "Review: minimum length should be 5" in flagged.questions[5].programming.unresolved
    score = compare_surveys(program.xml, program.xml)
    assert score.score == 1.0
    other = program.xml.replace('verify="range(0,999)"', 'verify="range(0,99)"')
    assert compare_surveys(other, program.xml).score < 1.0


def test_assigned_variable_and_grid_column_piping() -> None:
    """A least-fill cell variable can be referred to, and rows pipe from a grid's Yes column."""
    document = Questionnaire(
        id="a",
        title="Ad test",
        questions=[
            Question(
                id="qAID",
                type="grid",
                text="Have you heard of these brands?",
                matrix_items=["Boursin", "Alouette"],
                options=[Option(code=1, label="Yes"), Option(code=2, label="No")],
            ),
            Question(
                id="qFAM",
                type="grid",
                text="How familiar are you with each brand?",
                matrix_items=["Boursin", "Alouette"],
                options=[Option(code=1, label="Very"), Option(code=2, label="Not at all")],
                display_if=Comparison(op="in", ref="hType", value=[1, 2]),
                programming=ProgrammingSpec(row_condition=RowCondition(source="qAID", column=1)),
            ),
        ],
        derived_variables=[
            DerivedVariable(
                id="hType",
                definition="Least fill into digital exposed, digital control, FE exposed, FE control.",
                values=[DerivedValue(code=c, label=f"Cell {c}") for c in (1, 2, 3, 4)],
                unresolved=["Assigned by least fill"],
            )
        ],
    )
    assert spec_issues(document) == {}
    program = compile_decipher(document)
    assert program.validation_status != "failed", program.issues
    root = _root(program.xml)
    qfam = root.find(".//radio[@label='qFAM']")
    assert qfam.get("rowCond") == "qAID[row].c1"
    assert qfam.get("cond") == "(hType.r1 or hType.r2)"
    assert root.find(".//radio[@label='hType']") is not None
    assert "PROGRAMMER TODO: assign hType" in program.xml


def test_new_instruction_types_reach_the_xml() -> None:
    """Pipes, autopunch, cross-question checks, ask-once prompts, boxes, drop-downs, and timed terminates."""
    from app.schemas.questionnaire import AutoFill, Pipe, TerminateRule, Validation
    from app.services.programming_spec import _reversed_scale

    document = Questionnaire(
        id="n",
        title="New types",
        terminate_after="C2",
        questions=[
            Question(
                id="S11",
                type="single_select",
                text="Which PRO are you a member of?",
                options=[Option(code=1, label="ASCAP"), Option(code=2, label="BMI")],
                programming=ProgrammingSpec(dropdown=True),
            ),
            Question(
                id="S3",
                type="numeric",
                text="What is your age?",
                options=[Option(code=99, label="Prefer not to answer", terminate=True)],
                programming=ProgrammingSpec(
                    noanswer_codes=[99],
                    confirm_codes=[99],
                    confirm_message="Sorry! We need your exact age.",
                    terminate_rules=[
                        TerminateRule(
                            when=Comparison(op="lt", ref="S3", value=18), immediately=True
                        ),
                        TerminateRule(when=Comparison(op="gt", ref="S3", value=54)),
                    ],
                ),
            ),
            Question(
                id="C1",
                type="numeric",
                text="How many people live in your home?",
                programming=ProgrammingSpec(min_value=1, max_value=12),
            ),
            Question(
                id="C2",
                type="numeric",
                text="How many are children?",
                programming=ProgrammingSpec(
                    validations=[
                        Validation(
                            error_when=Comparison(op="gt", ref="C2", value_ref="C1"),
                            message="This cannot be more than the people in your home.",
                        )
                    ]
                ),
            ),
            Question(
                id="Q1",
                type="text",
                text="How satisfied are you with your [INSERT S11] membership? Name three brands.",
                programming=ProgrammingSpec(
                    boxes=3, pipes=[Pipe(placeholder="[INSERT S11]", source="S11")]
                ),
            ),
            Question(
                id="Q2",
                type="single_select",
                text="How many did you buy?",
                options=[Option(code=0, label="0"), Option(code=1, label="1-3")],
                display_if=Comparison(op="ne", ref="S11", value=1),
                programming=ProgrammingSpec(
                    autofill=AutoFill(code=0, when=Comparison(op="eq", ref="S11", value=1))
                ),
            ),
        ],
    )
    assert spec_issues(document) == {}, spec_issues(document)
    program = compile_decipher(document)
    assert program.validation_status != "failed", program.issues
    xml = program.xml
    root = _root(xml)
    assert root.find(".//select[@label='S11']/choice[@label='ch1']") is not None
    assert "(S11.val == S11.ch1.index)" in xml
    s3 = root.find(".//number[@label='S3']")
    assert "p.get('S3_confirm_asked')" in s3.find("validate").text
    labels = [e.get("label") for e in root.iter() if e.get("label")]
    # Under 18 ends at once; 55+ waits for the end of the screener (after C2).
    assert (
        labels.index("Term_S3_1")
        < labels.index("C1")
        < labels.index("C2")
        < labels.index("Term_S3_2")
    )
    assert "C2.ival &gt; C1.ival" in xml
    q1 = root.find(".//text[@label='Q1']")
    assert [r.get("label") for r in q1.findall("row")] == ["r1", "r2", "r3"]
    assert "${S11.selected.text if S11.selected else" in q1.find("title").text
    assert "Q2.val = Q2.r0.index" in xml
    flipped = _reversed_scale(
        [Option(code=c, label=str(c)) for c in (1, 2, 3)]
        + [Option(code=4, label="Don't know", exclusive=True)]
    )
    assert [o.code for o in flipped] == [3, 2, 1, 4]


def test_skip_on_a_derived_variable_uses_its_rows() -> None:
    """'IF hTYPE = 3 OR 4 SKIP TO qFE' hides the digital questions with hType rows, not .val."""
    from app.schemas.questionnaire import RoutingRule

    document = Questionnaire(
        id="k",
        title="Skip",
        questions=[
            Question(
                id="qA",
                type="single_select",
                text="First?",
                options=[Option(code=1, label="Yes"), Option(code=2, label="No")],
                routing=[
                    RoutingRule(when=Comparison(op="in", ref="hType", value=[3, 4]), go_to="qFE")
                ],
            ),
            Question(id="qDIG", type="text", text="Digital only?"),
            Question(id="qFE", type="text", text="Forced exposure?"),
        ],
        derived_variables=[
            DerivedVariable(
                id="hType",
                definition="Least fill.",
                values=[DerivedValue(code=c, label=f"Cell {c}") for c in (1, 2, 3, 4)],
            )
        ],
    )
    program = compile_decipher(document)
    assert program.validation_status != "failed", program.issues
    assert (
        _root(program.xml).find(".//textarea[@label='qDIG']").get("cond")
        == "not ((hType.r3 or hType.r4))"
    )
