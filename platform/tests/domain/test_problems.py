import copy

import pytest

from domain.problems import CatalogCase, WargameCatalog, validate_problem

CATALOG = {
    "board": WargameCatalog(
        cases={
            "board-sqli": CatalogCase(malicious=True, recorded=True),
            "board-xss": CatalogCase(malicious=True, recorded=False),
            "board-browse": CatalogCase(malicious=False, recorded=True),
        },
        objectives=frozenset({"db-dump"}),
    )
}

ROUND = {
    "problem": {"kind": "round", "wargame": "board", "side": "defence", "title": "Hold the board",
                "summary": "s", "body": "b", "published": False},
    "round": {"matchups": ["def_vs_bot", "pvp"], "probe_cases": ["board-sqli"], "objectives": ["db-dump"],
              "hp": {"budget": 100, "per_request": 1, "refused_x": 3, "burst_per_s": 5, "burst_x": 2},
              "benign_every_s": 30, "time_limit_s": None},
}

def errors(doc):
    return [(e.path, e.code) for e in validate_problem(doc, CATALOG)]


def changed(doc, edit):
    doc = copy.deepcopy(doc)
    edit(doc)
    return doc


def test_valid_documents_have_no_errors():
    assert errors(ROUND) == []


def test_the_document_must_carry_a_problem():
    assert errors([]) == [("", "not_an_object")]
    assert errors({}) == [("problem", "required")]


@pytest.mark.parametrize("edit, expected", [
    (lambda d: d["problem"].update(wargame="nowhere"), ("problem.wargame", "unknown_wargame")),
    (lambda d: d["problem"].update(kind="scenario"), ("problem.kind", "not_a_choice")),
    (lambda d: d["problem"].update(side="red"), ("problem.side", "not_a_choice")),
    (lambda d: d["problem"].update(title=" "), ("problem.title", "required")),
    (lambda d: d["problem"].update(published="yes"), ("problem.published", "not_a_boolean")),
    (lambda d: d.pop("round"), ("round", "required")),
    (lambda d: d["round"].update(matchups=[]), ("round.matchups", "required")),
    (lambda d: d["round"].update(matchups=["pvp", "atk_vs_bot"]), ("round.matchups[1]", "matchup_not_allowed")),
    (lambda d: d["round"].update(matchups=["solo"]), ("round.matchups[0]", "not_a_choice")),
    (lambda d: d["round"].update(probe_cases=["board-nope"]), ("round.probe_cases[0]", "unknown_case")),
    (lambda d: d["round"].update(probe_cases=["board-browse"]), ("round.probe_cases[0]", "not_malicious")),
    (lambda d: d["round"].update(probe_cases=["board-xss"]), ("round.probe_cases[0]", "not_recorded")),
    (lambda d: d["round"].update(objectives=["root"]), ("round.objectives[0]", "unknown_objective")),
    (lambda d: d["round"]["hp"].update(budget=0), ("round.hp.budget", "not_a_positive_integer")),
    (lambda d: d["round"]["hp"].update(burst_x=1.5), ("round.hp.burst_x", "not_a_positive_integer")),
    (lambda d: d["round"]["hp"].pop("refused_x"), ("round.hp.refused_x", "not_a_positive_integer")),
    (lambda d: d["round"]["hp"].update(per_request=True), ("round.hp.per_request", "not_a_positive_integer")),
    (lambda d: d["round"].update(time_limit_s=-1), ("round.time_limit_s", "not_a_positive_integer")),
    (lambda d: d["round"].update(benign_every_s=0), ("round.benign_every_s", "not_a_positive_integer")),
])
def test_round_errors_come_back_by_path(edit, expected):
    assert errors(changed(ROUND, edit)) == [expected]


def test_every_side_allows_pvp_and_only_its_own_bot_matchup():
    attack = changed(ROUND, lambda d: d["problem"].update(side="attack"))
    attack["round"]["matchups"] = ["pvp", "atk_vs_bot", "def_vs_bot"]
    both = changed(ROUND, lambda d: d["problem"].update(side="both"))
    both["round"]["matchups"] = ["pvp", "atk_vs_bot", "def_vs_bot"]

    assert errors(attack) == [("round.matchups[2]", "matchup_not_allowed")]
    assert errors(both) == []


def test_an_unknown_wargame_does_not_also_report_every_case():
    doc = changed(ROUND, lambda d: d["problem"].update(wargame="nowhere"))

    assert errors(doc) == [("problem.wargame", "unknown_wargame")]


def test_values_of_the_wrong_type_are_errors_not_crashes():
    doc = changed(ROUND, lambda d: (d["problem"].update(wargame=["board"]), d["round"].update(objectives=[{}])))

    assert errors(doc) == [("problem.wargame", "unknown_wargame"), ("round.objectives", "not_a_text_list")]
