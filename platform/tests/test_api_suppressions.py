from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from rules.suricata import RuleApplyError

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("a_session_is_open")]

RELOAD = ("kill", "-USR2", "1")
RULES = (
    '# FSL MVP baseline rules.\n\n'
    'alert http any any -> any any (msg:"FSL SQLi attempt - URI"; sid:9000001; rev:1;)\n\n'
    'alert http any any -> any any (msg:"FSL XSS attempt"; sid:9000003; rev:1;)\n'
)

class Suricata:

    def __init__(self, content=RULES):
        self.content = content
        self.applied = []

    def current(self, sensor, path=None):
        return self.content

    def apply(self, content, sensor, reload_command=None, path=None):
        self.applied.append(content)
        self.content = content

@pytest.fixture
def ids():
    fake = Suricata()
    with patch("api.views.suricata.current", fake.current), patch(
        "api.views.suricata.apply", fake.apply
    ):
        yield fake

def test_silencing_a_rule_comments_it_out_reloads_and_names_the_session(client, ids, a_session_is_open):
    response = client.post_json("/api/rules/suppressions/", {"sid": 9000001, "session": a_session_is_open.pk})
    listed = client.get("/api/rules/suppressions/").json()["suppressions"]

    assert response.status_code == 201
    assert response.json()["sid"] == 9000001
    assert ids.applied, "the IDS was never told"
    assert '#alert http any any -> any any (msg:"FSL SQLi attempt - URI"' in ids.content
    assert 'alert http any any -> any any (msg:"FSL XSS' in ids.content
    assert [s["session_id"] for s in listed] == [a_session_is_open.pk], (
        "a suppression that does not say which session it silenced cannot be told "
        "apart from one an earlier run left behind"
    )

@pytest.mark.parametrize("sid, status", [(4242, 404), ("all of them", 400)])
def test_a_sid_that_names_no_rule_changes_nothing(client, ids, sid, status):
    response = client.post_json("/api/rules/suppressions/", {"sid": sid})

    assert response.status_code == status
    assert not ids.applied
    assert client.get("/api/rules/suppressions/").json()["suppressions"] == []

def test_the_record_follows_what_the_ids_took(client, ids):
    with patch("api.views.suricata.apply", side_effect=RuleApplyError("bad config")):
        refused = client.post_json("/api/rules/suppressions/", {"sid": 9000001})
    assert refused.status_code == 400
    assert client.get("/api/rules/suppressions/").json()["suppressions"] == []

    created = client.post_json("/api/rules/suppressions/", {"sid": 9000001}).json()
    with patch("api.views.suricata.apply", side_effect=RuleApplyError("bad config")):
        response = client.post_json(f"/api/rules/suppressions/{created['id']}/restore/")

    assert response.status_code == 400
    assert [s["sid"] for s in client.get("/api/rules/suppressions/").json()["suppressions"]] == [9000001]

def test_a_suppression_holds_until_it_expires_and_then_puts_the_rule_back(client, ids):
    created = client.post_json(
        "/api/rules/suppressions/", {"sid": 9000001, "minutes": 30}
    ).json()
    live = client.get("/api/rules/suppressions/").json()
    assert [s["sid"] for s in live["suppressions"]] == [9000001] and live["restored"] == []
    assert "#alert" in ids.content

    from api.models import Suppression

    Suppression.objects.filter(pk=created["id"]).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    listed = client.get("/api/rules/suppressions/").json()

    assert listed["suppressions"] == [], "an expired suppression is still listed"
    assert [r["sid"] for r in listed["restored"]] == [9000001]
    assert ids.content == RULES, "the rule file did not come back byte for byte"

REWORDED = 'alert http any any -> any any (msg:"FSL SQLi attempt - URI, reworded"; sid:9000001; rev:1;)\n'

def refuses_a_duplicate_signature(ids):
    def apply(content, sensor, reload_command=None, path=None):
        active = [l for l in content.splitlines() if "sid:9000001" in l and not l.startswith("#")]
        if len(active) > 1:
            raise RuleApplyError(f'Duplicate signature "{active[-1]}"')
        ids.apply(content, sensor, reload_command, path)

    return patch("api.views.suricata.apply", apply)

def the_replacement_alone_carries_the_sid(content):
    from suppress import MARKER

    assert MARKER not in content
    assert [line for line in content.splitlines() if "sid:9000001" in line] == [REWORDED.strip()], (
        "the lift uncommented the silenced original beside the rule that replaced "
        "it: two active rules with one sid and rev, which suricata -T refuses as "
        "a duplicate signature on every try"
    )

@pytest.mark.parametrize("replaced", [False, True])
def test_a_suppression_can_be_lifted_by_hand_even_after_its_rule_was_replaced(client, ids, replaced):
    created = client.post_json("/api/rules/suppressions/", {"sid": 9000001}).json()
    if replaced:
        ids.content += REWORDED

    with refuses_a_duplicate_signature(ids):
        response = client.post_json(f"/api/rules/suppressions/{created['id']}/restore/")

    assert response.status_code == 200, response.content
    assert response.json()["restored_at"] is not None
    if replaced:
        assert "superseded" in response.json()["detail"]
        the_replacement_alone_carries_the_sid(ids.content)
    else:
        assert ids.content == RULES

def test_a_lift_whose_rule_was_replaced_meanwhile_is_done_once_and_says_so(client, ids):
    from api.models import Suppression

    created = client.post_json("/api/rules/suppressions/", {"sid": 9000001}).json()
    ids.content += REWORDED
    Suppression.objects.filter(pk=created["id"]).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    session_id = client.post_json("/api/sessions/", {}).json()["id"]

    with patch("api.views.elastic.fetch", return_value=([], None)), refuses_a_duplicate_signature(ids):
        first = client.post_json(f"/api/sessions/{session_id}/ingest/").json()["restored"]
        applied = len(ids.applied)
        second = client.post_json(f"/api/sessions/{session_id}/ingest/").json()["restored"]

    assert [(r["sid"], r["ok"]) for r in first] == [(9000001, True)]
    assert "superseded" in first[0]["detail"]
    assert second == [] and len(ids.applied) == applied, (
        "the lift was tried again on the next tick"
    )
    the_replacement_alone_carries_the_sid(ids.content)
    assert "FSL XSS attempt" in ids.content
