"""Fraud recommendation rules, the keyword route, and the workbook."""

import pandas as pd

from app.agents.intent import build_contract
from app.engines.cleaning_export import export_cleaning, workbook_row_check
from app.engines.cleaning_oe import PendingVerbatim, scan_open_ends
from app.engines.cleaning_rules import scan_closed
from app.engines.cleaning_score import kept_positions, recommend, validate_cleaning
from app.schemas.cleaning import VerbatimJudgement


def _variable(
    name: str, label: str, labels: dict[str, str] | None = None, text: bool = False
) -> dict:
    """Build one dictionary entry.

    Args:
        name: Variable name.
        label: Variable label.
        labels: Value labels.
        text: Whether the column is an open end.

    Returns:
        Dictionary entry.
    """
    return {
        "name": name,
        "label": label,
        "is_text": text,
        "value_labels": labels or {},
        "user_missing_values": [],
    }


def _scale() -> dict[str, str]:
    """Return a five-point scale.

    Returns:
        Value labels.
    """
    return {str(point): f"Point {point}" for point in range(1, 6)}


def _fraud_frame() -> tuple[pd.DataFrame, list[dict]]:
    """Build one clean row, one speeder, one straight-liner, one gibberish row, and one copy.

    Returns:
        Frame and dictionary.
    """
    scale = _scale()

    def grids(first: list[int], second: list[int]) -> dict[str, int]:
        row = {f"Q1_{index}": value for index, value in enumerate(first, start=1)}
        row.update({f"Q2_{index}": value for index, value in enumerate(second, start=1)})
        return row

    clean = grids([1, 2, 3, 4], [2, 4, 3, 1])
    rows = [
        {
            "respondent_id": "C1",
            "loi": 100,
            "weight": 1,
            "gender": 1,
            "age": 35,
            **clean,
            "Q99": "The battery lasts through a full work day and charges quickly.",
        },
        {
            "respondent_id": "S1",
            "loi": 10,
            "weight": 1,
            "gender": 2,
            "age": 40,
            **grids([2, 2, 3, 4], [1, 4, 3, 2]),
            "Q99": "It was fine overall and I would buy it again tomorrow.",
        },
        {
            "respondent_id": "L1",
            "loi": 100,
            "weight": 1,
            "gender": 2,
            "age": 42,
            **grids([5, 5, 5, 5], [1, 1, 1, 1]),
            "Q99": "I use it every morning before work and again at night.",
        },
        {
            "respondent_id": "G1",
            "loi": 100,
            "weight": 1,
            "gender": 1,
            "age": 33,
            **grids([1, 3, 2, 4], [4, 2, 3, 1]),
            "Q99": "asdfasdf",
        },
        {
            "respondent_id": "D1",
            "loi": 100,
            "weight": 1,
            "gender": 1,
            "age": 35,
            **clean,
            "Q99": "Delivery was slow but the product itself worked as promised.",
        },
    ]
    frame = pd.DataFrame(rows)
    variables = [
        _variable("respondent_id", "Respondent id"),
        _variable("loi", "Length of interview"),
        _variable("weight", "Weight"),
        _variable("gender", "Gender", {"1": "Female", "2": "Male"}),
        _variable("age", "Age"),
        *[_variable(f"Q1_{index}", "Agreement battery", scale) for index in range(1, 5)],
        *[_variable(f"Q2_{index}", "Satisfaction battery", scale) for index in range(1, 5)],
        _variable("Q99", "Why did you rate the brand that way?", text=True),
    ]
    return frame, variables


def test_known_fraud_dispositions() -> None:
    """A speeder is review, and straight-lining, gibberish, and an exact copy are remove."""
    frame, variables = _fraud_frame()
    report = recommend(frame, variables, dataset_id="data-1")
    by_id = {row.respondent_id: row for row in report.respondents}
    assert by_id["C1"].disposition == "keep"
    assert by_id["C1"].rule_ids == []
    assert by_id["S1"].disposition == "review"
    assert "speeding" in by_id["S1"].rule_ids
    assert by_id["L1"].disposition == "remove"
    assert by_id["L1"].rule_ids.count("straightline") == 1
    assert sum(flag.rule_id == "straightline" for flag in by_id["L1"].flags) == 2
    assert by_id["G1"].disposition == "remove"
    assert "oe_gibberish" in by_id["G1"].rule_ids
    assert by_id["D1"].disposition == "remove"
    assert "exact_duplicate" in by_id["D1"].rule_ids
    assert report.summary.keep_n + report.summary.review_n + report.summary.remove_n == 5
    assert report.summary.weighted_remove_share == 0.6
    assert report.summary.weighted_review_share == 0.2
    assert validate_cleaning(report)[0].status == "passed"
    assert all(check.status == "passed" for check in validate_cleaning(report))


def test_skipped_checks_when_columns_are_absent() -> None:
    """A file with no duration and no text still finishes and names the checks it could not run."""
    frame = pd.DataFrame({"respondent_id": ["A", "B"], "Q1": [1, 2]})
    variables = [
        _variable("respondent_id", "Respondent id"),
        _variable("Q1", "Overall"),
    ]
    report = recommend(frame, variables)
    skipped = " ".join(report.summary.skipped).lower()
    assert "duration" in skipped
    assert "open-end" in skipped
    assert report.summary.keep_n == 2
    assert report.summary.remove_n == 0
    assert report.summary.row_count == 2


def test_routed_blanks_are_not_nonresponse() -> None:
    """Blanks in routed columns do not count; a respondent who skips core questions does."""
    rows = []
    for index in range(10):
        row = {"respondent_id": f"R{index}"}
        row.update({f"C{item}": (index + item) % 5 + 1 for item in range(6)})
        # Reason: twelve routed columns answered only by respondent R0.
        row.update({f"R{item}": 3 if index == 0 else None for item in range(12)})
        rows.append(row)
    rows[9].update({f"C{item}": None for item in range(3)})
    frame = pd.DataFrame(rows)
    variables = [
        _variable("respondent_id", "Respondent id"),
        *[_variable(f"C{item}", f"Core {item}", _scale()) for item in range(6)],
        *[_variable(f"R{item}", f"Routed {item}", _scale()) for item in range(12)],
    ]
    report = recommend(frame, variables)
    flagged = {
        row.respondent_id for row in report.respondents if "high_nonresponse" in row.rule_ids
    }
    assert flagged == {"R9"}


def test_string_ids_and_captured_fields_are_not_open_ends() -> None:
    """A text uuid and captured panel fields are not scored as verbatims."""
    frame = pd.DataFrame(
        {
            "uuid": ["k3x9q2", "p7m1z8"],
            "psid": ["a8f3e1c9", "77b2d0e4"],
            "Q1": [1, 2],
        }
    )
    variables = [
        _variable("uuid", "uuid: Participant identifier", text=True),
        _variable("psid", "psid: Captured variable", text=True),
        _variable("Q1", "Overall"),
    ]
    report = recommend(frame, variables)
    assert [row.respondent_id for row in report.respondents] == ["k3x9q2", "p7m1z8"]
    assert all(row.rule_ids == [] for row in report.respondents)
    assert "open-end" in " ".join(report.summary.skipped).lower()


def test_missing_dataset_contract() -> None:
    """A fraud request without a dataset asks for the file instead of inventing respondents."""
    contract = build_contract(
        task_id="task-1",
        project_id="project-1",
        conversation_id="conversation-1",
        text="identify fraud respondents",
        variable_names=[],
        has_dataset=False,
    )
    assert contract.intent == "clean_data"
    assert contract.specialist == "cleaning"
    assert "dataset" in contract.missing_required


def test_near_duplicate_is_review() -> None:
    """95 percent agreement across 20 closed ends is review, and the earlier row stays."""
    columns = [f"C{index}" for index in range(1, 21)]
    first = {name: 1 for name in columns}
    second = {name: 1 for name in columns}
    second["C20"] = 2
    frame = pd.DataFrame([first, second])
    variables = [_variable(name, name) for name in columns]
    report = recommend(frame, variables)
    assert report.respondents[0].disposition == "keep"
    assert report.respondents[1].disposition == "review"
    assert "near_duplicate" in report.respondents[1].rule_ids


def test_trap_fail_removes() -> None:
    """A labeled attention check that is not the pass code is removed."""
    frame = pd.DataFrame({"respondent_id": ["A", "B"], "TRAP": [1, 3]})
    variables = [
        _variable("respondent_id", "Respondent id"),
        _variable(
            "TRAP",
            "Attention check please select 3",
            {"1": "No", "2": "No", "3": "Correct"},
        ),
    ]
    report = recommend(frame, variables)
    assert report.respondents[0].disposition == "remove"
    assert "trap_fail" in report.respondents[0].rule_ids
    assert report.respondents[1].disposition == "keep"


def test_one_weak_open_end_keeps_and_two_review() -> None:
    """One off-topic answer keeps the row with its flag. A second weak answer reviews it."""
    frame = pd.DataFrame(
        {
            "respondent_id": ["A", "B"],
            "Q98": [
                "The checkout page loaded quickly on my phone.",
                "My cat likes sitting on the keyboard all day.",
            ],
            "Q99": [
                "I want to talk about the weather instead of this brand.",
                "I want to talk about football instead of this brand.",
            ],
        }
    )
    variables = [
        _variable("respondent_id", "Respondent id"),
        _variable("Q98", "What did you like about the site?", text=True),
        _variable("Q99", "Why did you choose it?", text=True),
    ]
    scan = scan_open_ends(frame, [(item["name"], item["label"]) for item in variables[1:]])
    ids = {(item.source_row_id, item.variable): item.surrogate_id for item in scan.pending}
    note = "Not about the brand."
    report = recommend(
        frame,
        variables,
        judgements=[
            VerbatimJudgement(surrogate_id=ids[(0, "Q98")], label="substantive"),
            VerbatimJudgement(surrogate_id=ids[(0, "Q99")], label="off_topic", note=note),
            VerbatimJudgement(surrogate_id=ids[(1, "Q98")], label="off_topic", note=note),
            VerbatimJudgement(surrogate_id=ids[(1, "Q99")], label="off_topic", note=note),
        ],
    )
    first, second = report.respondents
    assert first.disposition == "keep"
    assert first.rule_ids == ["oe_off_topic"]
    assert second.disposition == "review"
    assert len(second.flags) == 2


def test_unreviewed_open_end_is_review() -> None:
    """An undecided verbatim stays in review when semantic review does not run."""
    frame = pd.DataFrame(
        {"respondent_id": ["A"], "Q99": ["The battery lasts through a full work day."]}
    )
    variables = [
        _variable("respondent_id", "Respondent id"),
        _variable("Q99", "Why did you choose it?", text=True),
    ]
    plain = recommend(frame, variables)
    assert plain.respondents[0].disposition == "keep"
    reviewed = recommend(
        frame,
        variables,
        unreviewed_rows={0},
        semantic_review="Semantic review was not run because no API key is set.",
    )
    assert reviewed.respondents[0].disposition == "review"
    assert "oe_unreviewed" in reviewed.respondents[0].rule_ids


def test_workbook_matches_respondent_count() -> None:
    """The respondent sheet has one data row for every person in the recommendation."""
    frame, variables = _fraud_frame()
    report = recommend(frame, variables, dataset_id="data-1")
    payload = export_cleaning(report)
    assert workbook_row_check(payload, report.summary.row_count).status == "passed"


def test_apply_keeps_review_rows() -> None:
    """Removal keeps review and drops only remove."""
    frame, variables = _fraud_frame()
    report = recommend(frame, variables, dataset_id="data-1")
    kept = kept_positions(report, len(frame))
    dispositions = [report.respondents[index].disposition for index in kept]
    assert "remove" not in dispositions
    assert "review" in dispositions
    assert len(kept) == report.summary.keep_n + report.summary.review_n


def test_code_text_columns_are_not_open_ends() -> None:
    """A ZIP or state code stored as text is not sent to open-end review."""
    frame = pd.DataFrame(
        {
            "respondent_id": ["A", "B", "C"],
            "zip": ["37130", "10001", "94110"],
            "state": ["MD", "NY", "CA"],
            "Q9": ["Fast support", "Good price", "Easy setup"],
        }
    )
    variables = [
        _variable("respondent_id", "Respondent id"),
        _variable("zip", "In which zip code is your primary residence?", text=True),
        _variable("state", "State code", text=True),
        _variable("Q9", "What do you like most?", text=True),
    ]
    closed = scan_closed(frame, variables)
    assert [name for name, _ in closed.text_columns] == ["Q9"]


async def test_review_sends_each_text_once_and_survives_a_failed_batch(monkeypatch) -> None:
    """Duplicates share one label, and a failed batch leaves only its rows in review."""
    from app.agents import cleaning_agent
    from app.services import cleaning_run

    pending = [
        PendingVerbatim(f"v{index:04d}", index, "Q9", "What do you like?", text)
        for index, text in enumerate(["Great price!", "great price", "Fast support", "lol"])
    ]
    sent: list[list[str]] = []

    async def fake_run(settings, *, prompt, **kwargs):
        ids = [line.split("\t")[0] for line in prompt.splitlines()[1:]]
        sent.append(ids)
        if "v0003" in ids:
            raise RuntimeError("batch failed")
        return cleaning_agent.VerbatimBatch(
            judgements=[VerbatimJudgement(surrogate_id=item, label="substantive") for item in ids]
        )

    monkeypatch.setattr(cleaning_agent, "run_structured", fake_run)
    monkeypatch.setattr(cleaning_agent, "_BATCH", 2)
    monkeypatch.setattr(cleaning_run, "coding_ready", lambda settings: True)
    stages: list[str] = []
    judgements, unreviewed, note = await cleaning_run._review(
        None, pending, "session", stages.append
    )
    assert sorted(item for batch in sent for item in batch) == ["v0000", "v0002", "v0003"]
    labeled = {item.surrogate_id for item in judgements}
    assert labeled == {"v0000", "v0001", "v0002"}
    assert 3 in unreviewed
    assert 0 not in unreviewed and 1 not in unreviewed
    assert "3 distinct verbatims (4 answers)" in note
    assert stages[0] == "Reading 3 distinct open ends"
