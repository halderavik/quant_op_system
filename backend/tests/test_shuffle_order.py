"""'Same order as' questions follow Decipher's shuffleBy rules."""

import xml.etree.ElementTree as ET

from app.engines.decipher import compile_decipher
from app.engines.decipher_repair import repair_survey_xml
from app.schemas.questionnaire import Option, ProgrammingSpec, Question, Questionnaire

# The two messages Decipher returned for the BrewCo survey.
DECIPHER_ERRORS = [
    "survey: The number of rows on the shuffledBy question is different",
    "survey: ShuffleBy set but shuffle=rows/cols not selected",
]


def _brands(
    qid: str, *, random: bool = False, same_as: str | None = None, extra: bool = False
) -> Question:
    """A brand list; ``extra`` adds a fifth brand instead of Other and None."""
    options = [Option(code=i, label=f"Brand {i}") for i in range(1, 5)]
    if extra:
        options.append(Option(code=5, label="Brand 5"))
    else:
        options += [
            Option(code=98, label="Other", open_text=True),
            Option(code=99, label="None of these", anchor=True, exclusive=True),
        ]
    return Question(
        id=qid,
        type="single_select",
        text=f"{qid} brands",
        options=options,
        randomize_options=random,
        programming=ProgrammingSpec(same_order_as=same_as),
    )


def _build(*questions: Question):
    program = compile_decipher(Questionnaire(id="q", title="t", questions=list(questions)))
    root = ET.fromstring(program.xml)
    return program, {node.get("label"): node for node in root.iter("radio")}


def _valid_shuffle_by(nodes: dict[str, ET.Element]) -> None:
    """Every shuffleBy follows Decipher's two rules."""
    for node in nodes.values():
        leader = node.get("shuffleBy")
        if leader:
            assert "rows" in (node.get("shuffle") or ""), node.get("label")
            assert len(node.findall("row")) == len(nodes[leader].findall("row")), node.get("label")


def test_same_list_follows_the_shuffled_leader() -> None:
    """Same rows as a shuffled question: shuffleBy plus a shuffle, with None pinned."""
    _, nodes = _build(_brands("Q2", random=True), _brands("Q3", same_as="Q2"))
    assert nodes["Q3"].get("shuffleBy") == "Q2"
    assert nodes["Q3"].get("shuffle") == "rows"
    pinned = {row.get("label") for row in nodes["Q3"].findall("row") if row.get("randomize") == "0"}
    assert pinned == {"r98", "r99"}
    _valid_shuffle_by(nodes)


def test_a_different_list_shuffles_on_its_own_with_a_warning() -> None:
    """Q12 (five brands) can't share Q2's order (four brands, Other, None)."""
    program, nodes = _build(_brands("Q2", random=True), _brands("Q12", same_as="Q2", extra=True))
    assert nodes["Q12"].get("shuffleBy") is None
    assert nodes["Q12"].get("shuffle") == "rows"
    assert any("Q12 should keep the same order as Q2" in item for item in program.warnings)
    _valid_shuffle_by(nodes)


def test_a_chain_follows_a_question_that_shuffles_because_it_follows() -> None:
    """Q13 follows Q12, which only shuffles because it follows Q2: Q13 still shuffles."""
    _, nodes = _build(
        _brands("Q2", random=True),
        _brands("Q12", same_as="Q2", extra=True),
        _brands("Q13", same_as="Q12", extra=True),
    )
    assert nodes["Q13"].get("shuffleBy") == "Q12"
    assert nodes["Q13"].get("shuffle") == "rows"
    _valid_shuffle_by(nodes)


def test_following_a_fixed_order_needs_no_shuffle_by() -> None:
    """ "Same order as" a list that isn't shuffled is already the same order."""
    _, nodes = _build(_brands("Q2"), _brands("Q3", same_as="Q2"))
    assert nodes["Q3"].get("shuffleBy") is None and nodes["Q3"].get("shuffle") is None


def test_repair_removes_the_links_decipher_refused() -> None:
    """Decipher's two shuffleBy errors remove only the bad links before the next upload."""
    xml = """<survey name="s" alt="t">
<radio label="Q2" shuffle="rows"><row label="r1">A</row><row label="r2">B</row><row label="r99">None</row></radio>
<radio label="Q3" shuffle="rows" shuffleBy="Q2"><row label="r1">A</row><row label="r2">B</row><row label="r99">None</row></radio>
<radio label="Q12" shuffle="rows" shuffleBy="Q2"><row label="r1">A</row><row label="r2">B</row></radio>
<radio label="Q13" shuffleBy="Q12"><row label="r1">A</row><row label="r2">B</row></radio>
</survey>"""
    repaired = repair_survey_xml(xml, DECIPHER_ERRORS)
    assert repaired.changed
    nodes = {node.get("label"): node for node in ET.fromstring(repaired.xml).iter("radio")}
    assert nodes["Q3"].get("shuffleBy") == "Q2"  # valid, kept
    assert nodes["Q12"].get("shuffleBy") is None  # different number of rows
    assert nodes["Q13"].get("shuffleBy") is None  # no shuffle of its own
    assert "Q12" in repaired.fixes[0] and "Q13" in repaired.fixes[0]
