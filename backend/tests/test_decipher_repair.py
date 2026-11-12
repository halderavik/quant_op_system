"""Correct survey XML from the errors Decipher returns."""

from app.engines.decipher_repair import repair_survey_xml

_SURVEY = """<?xml version="1.0" encoding="UTF-8"?>
<survey name="Coffee" alt="Coffee" compat="153">
  <!-- Sample: adults -->
  <radio label="S1">
    <title>What is your age?</title>
    <note>Ask -- all.</note>
    <row label="r1">18-24</row>
  </radio>
  <checkbox label="S2">
    <title>Which brands?</title>
    <note>Select all.</note>
    <row label="r1">A</row>
  </checkbox>
</survey>
"""


def test_repair_sets_delphi_and_moves_notes() -> None:
    """Compat and note errors become a survey attribute and comments."""
    repaired = repair_survey_xml(
        _SURVEY,
        [
            "survey: Surveys at compat 151+ require delphi='1' setting",
            "This tag (Note) is not permitted inside a Radio tag",
            "This tag (Note) is not permitted inside a Checkbox tag",
        ],
    )
    assert repaired.changed
    assert 'delphi="1"' in repaired.xml
    assert "<note" not in repaired.xml
    assert "Sample: adults" in repaired.xml
    assert "S1: Ask - all." in repaired.xml
    assert "S2: Select all." in repaired.xml
    assert "What is your age?" in repaired.xml
    assert repaired.xml.index("S1: Ask - all.") < repaired.xml.index('label="S1"')


def test_repair_moves_a_tag_and_drops_only_the_named_attribute() -> None:
    """A forbidden child is moved, and an attribute is removed only on its tag."""
    xml = """<survey compat="153" delphi="1">
  <radio label="Q1" verify="email">
    <html>Shown before the question.</html>
    <title>Email</title>
  </radio>
  <number label="Q2" verify="range(0,10)"/>
</survey>"""
    repaired = repair_survey_xml(
        xml,
        [
            "This tag (html) is not permitted inside a radio tag",
            "Attribute 'verify' is not permitted on a radio tag",
        ],
    )
    assert repaired.changed
    assert repaired.xml.index("<html>") < repaired.xml.index("<radio")
    assert 'label="Q1"' in repaired.xml and "verify" not in repaired.xml.split("<number")[0]
    assert 'verify="range(0,10)"' in repaired.xml
    assert "Shown before the question." in repaired.xml


def test_unknown_or_broken_xml_is_left_unchanged() -> None:
    """An unrecognized message, or a document that will not parse, is not rewritten."""
    unknown = repair_survey_xml(_SURVEY, ["bad tag", "unknown element"])
    assert unknown.changed is False
    assert unknown.xml == _SURVEY
    assert unknown.fixes == []
    broken = repair_survey_xml(
        "<survey>",
        ["Surveys at compat 151+ require delphi='1' setting"],
    )
    assert broken.changed is False
    assert broken.xml == "<survey>"


def test_rejected_style_falls_back_to_the_plain_question() -> None:
    """A style Decipher cannot apply is removed so the survey still uploads."""
    xml = (
        '<survey name="Coffee" state="testing">'
        '<select label="Q6" uses="ranksort.7" minRanks="5" unique="none,cols">'
        '<title>Rank these</title><row label="r1">A</row><choice label="ch1">1</choice>'
        "</select>"
        '<radio label="Q7"><title>Pick</title><row label="r1">A</row></radio>'
        "</survey>"
    )
    repaired = repair_survey_xml(
        xml,
        [
            "survey: while using style 'lib/steam/ranksort/v7': "
            "The attribute 'minRanks' is required to be specified but was not"
        ],
    )
    assert repaired.changed
    assert "uses=" not in repaired.xml
    assert "minRanks" not in repaired.xml
    assert 'unique="none,cols"' in repaired.xml
    assert repaired.fixes == [
        "Removed the ranksort style from Q6, so those questions use Decipher's plain layout."
    ]
