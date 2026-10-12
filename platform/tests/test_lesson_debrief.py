from unittest.mock import patch

import pytest
from django.utils import timezone

from api.models import Case, Detection, Session
from rules import crs
from tests.test_lesson_api import HELD, Stand, attacker

pytestmark = pytest.mark.django_db

O_BRIEN = "board-normal-search-with-apostrophe"
EXCLUSION = {"rule_id": 920273, "target": "ARGS:q", "path": "/search/"}
SQLMAP_HELD = {"board-sqli-orderby-sqlmap": HELD, "board-sqli-orderby-sqlmap-tamper": HELD}

def debrief(client, session):
    return client.get(f"/api/sessions/{session.pk}/lesson/debrief/")

@pytest.fixture
def passed(client):
    stand = Stand()
    fire, _ = attacker(dict(SQLMAP_HELD, **{O_BRIEN: "http_code=403\n"}))
    with patch("range.docker.Docker.runner", stand.runner()), patch("api.views.harness.fire", fire):
        opened = client.post_json("/api/sessions/", {"guidance": True}).json()
    session = Session.objects.get(pk=opened["id"])
    seeded = session.cases.get(name=O_BRIEN)
    Detection.objects.create(session=session, detection_id="d1", source="modsecurity", signature="920273",
                             timestamp=timezone.now(), marker=seeded.case_id,
                             raw={"request": {"method": "GET", "uri": "/search/?q=O%27Brien"}})
    Detection.objects.create(session=session, detection_id="d2", source="modsecurity", signature="942100",
                             timestamp=timezone.now(), marker=session.browse_marker, raw={})
    client.post_json(f"/api/sessions/{session.pk}/lesson/hints/", {"step": "rule", "level": "hint"})
    client.post_json(f"/api/sessions/{session.pk}/lesson/steps/find/", {"state": "skipped"})
    stand.files[(session.pk, "gateway")] = crs.rendered({"paranoia": 4, "exclusions": [EXCLUSION]})
    fire, _ = attacker(SQLMAP_HELD)
    with patch("range.docker.Docker.runner", stand.runner()), patch("api.views.harness.fire", fire):
        client.post_json(f"/api/sessions/{session.pk}/verify/")
    return session

def test_the_debrief_tells_the_pass_the_change_the_cases_before_and_after_and_what_remains(client, passed):
    told = debrief(client, passed).json()

    assert told["overview"]["passed"] is True and told["overview"]["verified"] == 1
    assert (told["overview"]["mode"], told["overview"]["fix"]) == ("guided", "path_target")
    assert told["overview"]["help"] == {"hints": 1, "skipped": 1, "done_for_me": 0}
    assert told["change"]["added"] == [EXCLUSION] and told["change"]["removed"] == []
    assert told["change"]["before"] == {"paranoia": 4, "exclusions": []}
    assert told["change"]["diff"] == [
        '+SecRule REQUEST_FILENAME "@beginsWith /search/" "id:10001,phase:1,pass,nolog,ctl:ruleRemoveTargetById=920273;ARGS:q"',
    ]
    cases = {row["name"]: (row["before"], row["after"]) for row in told["cases"]}
    assert cases[O_BRIEN] == ("blocked", "served")
    assert cases["board-sqli-orderby-sqlmap"] == ("held", "held")
    assert told["risk"] == [["lesson.risk.path_target", []], ["lesson.risk.replayed", [2]]]

def test_the_debrief_s_evidence_is_the_session_s_own_records_of_the_lesson_s_cases_and_reads_no_elasticsearch(client, passed):
    with patch("ingest.elastic.fetch", side_effect=AssertionError("the debrief must not read Elasticsearch")):
        told = debrief(client, passed).json()

    assert [(row["signature"], row["phase"], row["case"], row["path"]) for row in told["evidence"]] == [
        ("920273", "seed", O_BRIEN, "/search/?q=O%27Brien"),
    ], "a browse record is not the lesson's evidence"
    assert told["at"]["opened"] and told["at"]["verified"], "times are in the API for agents"

def test_a_debrief_is_only_for_a_lesson_and_before_any_verify_it_says_nothing_passed(client):
    plain = Session.objects.create(scenario="board", baseline={})
    fresh = Session.objects.create(scenario="board", baseline={}, guidance=True)

    told = debrief(client, fresh).json()

    assert debrief(client, plain).status_code == 400
    assert (told["overview"]["passed"], told["overview"]["verified"]) == (None, 0)
    assert told["change"]["after"] is None and [row["after"] for row in told["cases"]] == [None] * 6
