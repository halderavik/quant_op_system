"""Scoring generated Decipher XML against a hand-programmed file."""

from app.engines.decipher_similarity import compare_questionnaire

_SURVEY = """<survey name="t">
<radio label="S14"><row label="r1">A</row><row label="r2">B</row>
<col label="c1">No</col><col label="c5">Yes</col></radio>
<radio label="PU4" rowCond="{cond}"><row label="r1">A</row><row label="r2">B</row>
<col label="c1">Low</col><col label="c2">High</col></radio>
</survey>"""


def test_row_then_column_and_column_then_row_piping_match():
    """S14[row].c5 and S14.c5[row] pick the same grid cell, so they score as a match."""
    ours = _SURVEY.format(cond="S14[row].c5")
    reference = _SURVEY.format(cond="S14.c5[row]")
    result = compare_questionnaire(ours, reference, {"S14", "PU4"})
    piping = [c for c in result.checks if c.check == "row piping"]
    assert piping and all(c.passed for c in piping)


def test_different_piping_sources_do_not_match():
    """Piping from another question still counts as a miss."""
    ours = _SURVEY.format(cond="S13[row]")
    reference = _SURVEY.format(cond="S14.c5[row]")
    result = compare_questionnaire(ours, reference, {"S14", "PU4"})
    assert not all(c.passed for c in result.checks if c.check == "row piping")
