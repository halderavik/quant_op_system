"""Intent routing for study briefs, questionnaire edits, and analysis requests."""

from app.agents.intent import build_contract
from app.schemas.project import TaskContract

_COFFEE_BRIEF = """
Audience: Adults 18 or older who live in the United States and bought coffee for home use in the past 3 months.
Sample: 600 completed online interviews. Target length is 12 minutes. This is a programming target, not a verified timing study.
Eligibility: Age 18 or older, resident of the United States, and bought coffee for home use at least once in the past 3 months. Terminate anyone who fails any of those three checks. Do not terminate on gender, age band, region, or income.
Quotas: Gender 50% female and 50% male, with non-binary and prefer-not-to-answer accepted but not quota-controlled. Age bands 18–34, 35–54, and 55+ at 30% / 40% / 30%. Census region Northeast, Midwest, South, and West at 18% / 21% / 38% / 23%.
Methodology: One question per screen, except the attribute grid, which is one screen. Randomize brand lists and attribute rows. Keep Other, None of these, and Prefer not to answer last, fixed, and mutually exclusive. Do not add brands, quotas, or terminate rules that are not listed here. Do not include a MaxDiff or conjoint exercise.
Objectives:
- Confirm the respondent is an eligible home-coffee buyer before the main interview.
- Measure unaided and aided awareness of the listed coffee brands.
- Describe the path to purchase: brands used, brand used most often, frequency, and last channel.
- Measure attribute ratings, satisfaction, and likelihood to recommend the brand used most often.
- Separate loyal buyers from switchers with a hidden punch for later segmentation.
- Capture one open-ended reason tied to the recommendation score.
Brands, in this order before randomization: Northstar, Harbor & Co., Lumen, Field & Co., Store brand. Do not add any other brand.
"""


def _contract(
    text: str,
    *,
    has_dataset: bool = False,
    has_questionnaire: bool = False,
    continuing: bool = False,
    has_tabspec: bool = False,
    offered_tabspec: bool = False,
) -> TaskContract:
    """Build a contract with no dataset variables.

    Args:
        text: User message.
        has_dataset: Whether a dataset is loaded.
        has_questionnaire: Whether a questionnaire is already saved.
        continuing: Whether the previous turn published a questionnaire.
        has_tabspec: Whether a tab spec is already saved.
        offered_tabspec: Whether the previous reply asked for a tab spec.

    Returns:
        Task contract.
    """
    return build_contract(
        task_id="task-1",
        project_id="project-1",
        conversation_id="conversation-1",
        text=text,
        variable_names=[],
        has_dataset=has_dataset,
        has_questionnaire=has_questionnaire,
        continuing=continuing,
        has_tabspec=has_tabspec,
        offered_tabspec=offered_tabspec,
    )


def test_pasted_study_brief_drafts_a_questionnaire() -> None:
    """A brief that mentions segmentation, open ends, and MaxDiff still drafts a survey."""
    contract = _contract(_COFFEE_BRIEF)
    assert contract.intent == "create_questionnaire"
    assert contract.specialist == "questionnaire"
    assert contract.missing_required == []


def test_short_brief_and_question_edit_stay_on_the_questionnaire() -> None:
    """Two brief labels are enough, and a question edit does not ask for SPSS."""
    brief = _contract("Audience: Adults 18+ in Canada\nObjectives:\n- Track awareness and NPS\n")
    edit = _contract("change Q3 so non-buyers skip the brand battery")
    assert brief.intent == "create_questionnaire"
    assert brief.missing_required == []
    assert edit.intent == "revise_questionnaire"
    assert edit.missing_required == []


def test_adding_a_question_revises_the_saved_instrument() -> None:
    """An income-bracket request edits the questionnaire instead of saving a note."""
    edit = _contract(
        "can you add a income question with different income brackets",
        has_questionnaire=True,
    )
    follow_up = _contract(
        "use these brackets: Under $25,000, $25,000 to $49,999, $50,000 or more",
        has_questionnaire=True,
        continuing=True,
    )
    assert edit.intent == "revise_questionnaire"
    assert follow_up.intent == "revise_questionnaire"
    assert edit.missing_required == []


def test_follow_up_does_not_steal_a_table_or_a_note() -> None:
    """A crosstab or a codename question stays on its own path after a draft."""
    table = _contract("Q5 by gender", has_dataset=True, has_questionnaire=True, continuing=True)
    note = _contract(
        "What is the project codename?",
        has_questionnaire=True,
        continuing=True,
    )
    removed = _contract("delete the chart from the report", has_questionnaire=True)
    assert table.intent == "run_crosstab"
    assert note.intent == "general_task"
    assert removed.intent == "general_task"


def test_analysis_follow_up_is_not_a_questionnaire_edit() -> None:
    """Answering an analysis question resumes segmentation instead of editing a survey."""
    reply = (
        "yes remove those 9 empty Q4 features and five empty profiling variables. "
        "Then run the task"
    )
    alone = _contract(reply, has_dataset=True)
    resumed = build_contract(
        task_id="task-1",
        project_id="project-1",
        conversation_id="conversation-1",
        text=reply,
        variable_names=["Q4r1", "Q15r1"],
        has_dataset=True,
        analysis_followup=True,
        prior_analysis_request="I want to run segmentation with Q15r1, Q4r1, Q4r2",
    )
    assert alone.intent != "revise_questionnaire"
    assert resumed.intent == "run_analysis"
    assert "Q15r1" in resumed.user_request
    assert "Follow-up instruction:" in resumed.user_request
    assert resumed.missing_required == []


def test_decipher_request_does_not_revise_the_questionnaire() -> None:
    """Survey XML and Decipher programming stay off the questionnaire editor."""
    program = _contract(
        "program this survey in decipher",
        has_questionnaire=True,
        continuing=True,
    )
    xml = _contract("generate the survey XML", has_questionnaire=True)
    named = _contract("program this questionnaire in decipher", has_questionnaire=True)
    edit = _contract("add a question about income", has_questionnaire=True)
    assert program.intent == "program_decipher"
    assert program.specialist == "decipher"
    assert xml.intent == "program_decipher"
    assert named.intent == "program_decipher"
    assert edit.intent == "revise_questionnaire"


def test_saved_spec_runs_when_the_user_asks_for_its_cross_tabs() -> None:
    """A request that points at the spec runs that spec and does not ask for one row."""
    named = "generate cross-tabs based on the specs"
    ready = _contract(named, has_dataset=True, has_tabspec=True)
    from_plan = _contract("run the crosstabs from the tab spec", has_dataset=True, has_tabspec=True)
    missing_spec = _contract(named, has_dataset=True)
    assert ready.intent == "run_saved_tabspec"
    assert ready.missing_required == []
    assert from_plan.intent == "run_saved_tabspec"
    assert from_plan.intent != "build_tabspec"
    assert "row_variable" not in missing_spec.missing_required
    assert missing_spec.intent == "run_saved_tabspec"


def test_named_banner_and_new_spec_stay_on_their_own_paths() -> None:
    """One named table still runs alone, and authoring a spec does not execute one."""
    table = _contract("Q5 by gender", has_dataset=True, has_tabspec=True)
    author = _contract("build a tab spec", has_tabspec=True)
    drafted = _contract("generate a tab spec", has_tabspec=True)
    bare = _contract("run a crosstab", has_dataset=True)
    spaced = _contract("generate the cross tabs", has_dataset=True, has_tabspec=True)
    assert table.intent == "run_crosstab"
    assert table.provided_fields["row_variable"] == "Q5"
    assert table.provided_fields["banner_variable"] == "gender"
    assert author.intent == "build_tabspec"
    assert drafted.intent == "build_tabspec"
    assert bare.missing_required == ["row_variable", "banner_variable"]
    assert spaced.intent == "run_saved_tabspec"
    assert spaced.missing_required == []


def test_hyphenated_build_requests_author_a_tab_spec() -> None:
    """Uploaded-data wording that names tab-specs starts the spec, not a note."""
    hyphen = _contract("can you please build tab-specs for this data", has_dataset=True)
    singular = _contract("build a tab-spec from this file", has_dataset=True)
    assert hyphen.intent == "build_tabspec"
    assert hyphen.specialist == "tabspec"
    assert hyphen.missing_required == []
    assert singular.intent == "build_tabspec"


def test_cross_tab_spec_is_authored_even_when_a_spec_exists() -> None:
    """Building the cross-tab spec writes a plan and does not try to run tables."""
    fresh = _contract("can you build the cross-tab spec for this uploaded data", has_dataset=True)
    again = _contract(
        "can you build the cross-tab spec for this uploaded data",
        has_dataset=True,
        has_tabspec=True,
    )
    tables = _contract(
        "generate cross-tabs based on the specs",
        has_dataset=True,
        has_tabspec=True,
    )
    assert fresh.intent == "build_tabspec"
    assert again.intent == "build_tabspec"
    assert tables.intent == "run_saved_tabspec"


def test_build_it_follows_the_missing_spec_reply_only() -> None:
    """'can you build it' authors a spec after that offer, and stays a note otherwise."""
    follow = _contract("can you build it", offered_tabspec=True)
    bare = _contract("can you build it")
    named = _contract("Q5 by gender", has_dataset=True, offered_tabspec=True)
    assert follow.intent == "build_tabspec"
    assert bare.intent == "general_task"
    assert named.intent == "run_crosstab"


def test_analysis_and_coding_requests_still_need_data() -> None:
    """A segmentation run or open-end coding job is not treated as a study brief."""
    analysis = _contract("Run a segmentation with variables trust and age")
    coding = _contract("Code the open-ended responses in column comment")
    assert analysis.intent == "run_analysis"
    assert "dataset" in analysis.missing_required
    assert coding.intent == "code_open_ends"
    assert "dataset" in coding.missing_required


def test_pam_gower_is_an_analysis_request() -> None:
    """Naming PAM with Gower routes to analysis when a dataset is loaded."""
    contract = _contract("Run PAM with Gower distance on the feature battery", has_dataset=True)
    assert contract.intent == "run_analysis"
    assert contract.missing_required == []
