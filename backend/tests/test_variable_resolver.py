"""Plain-language variable roles are filled from the labels, and only with real columns."""

from types import SimpleNamespace

from app.agents.orchestrator import _roles_to_resolve
from app.agents.variable_resolver import RoleMatch, RoleMatches, apply_matches

NAMES = {"Q18", "S6", "Q10r1", "Q10r2", "Q27", "Q28"}


def test_only_real_columns_fill_a_role() -> None:
    found = RoleMatches(
        roles=[
            RoleMatch(role="dependent", columns=["Q18"]),
            RoleMatch(role="predictors", columns=["Q10r1", "Q10r2", "Q10r99"]),
            RoleMatch(role="banner_variable", columns=["Gender"]),
            RoleMatch(role="group", columns=["S6"]),
        ]
    )
    out = apply_matches(found, ["dependent", "predictors", "banner_variable"], NAMES)
    assert out == {"dependent": "Q18", "predictors": ["Q10r1", "Q10r2"]}


def test_two_candidates_for_one_column_stay_missing() -> None:
    found = RoleMatches(roles=[RoleMatch(role="row_variable", columns=["Q18", "Q27"])])
    assert apply_matches(found, ["row_variable"], NAMES) == {}


def _contract(intent: str, missing: list[str], text: str, fields: dict | None = None):
    return SimpleNamespace(
        intent=intent, missing_required=missing, user_request=text, provided_fields=fields or {}
    )


def test_which_roles_are_resolved() -> None:
    variables = [{"name": "Q27", "is_text": True}, {"name": "Q28", "is_text": True}]
    assert _roles_to_resolve(
        _contract("run_analysis", ["dependent", "predictors"], "drivers of recommending BrewCo"),
        variables,
    ) == ["dependent", "predictors"]
    assert _roles_to_resolve(
        _contract("autocode_open_ends", [], "Auto-code the reasons for the score"), variables
    ) == ["response_variable"]
    assert _roles_to_resolve(_contract("autocode_open_ends", [], "Auto-code Q27"), variables) == []
    # Another missing item (a dataset) still asks the user once for everything.
    assert (
        _roles_to_resolve(
            _contract("run_analysis", ["dependent", "cleaning_recommendation"], "x"), variables
        )
        == []
    )
