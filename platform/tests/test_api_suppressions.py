from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from rules.suricata import RuleApplyError

pytestmark = pytest.mark.django_db

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

    def current(self, sensor):
        return self.content

    def apply(self, content, sensor, reload_command=None):
        self.applied.append(content)
        self.content = content

@pytest.fixture
def ids():
    fake = Suricata()
    with patch("api.views.suricata.current", fake.current), patch(
        "api.views.suricata.apply", fake.apply
    ):
        yield fake

def test_silencing_a_rule_comments_it_out_and_reloads(client, ids):
    response = client.post_json("/api/rules/suppressions/", {"sid": 9000001})

    assert response.status_code == 201
    assert response.json()["sid"] == 9000001
    assert ids.applied, "the IDS was never told"
    assert '#alert http any any -> any any (msg:"FSL SQLi attempt - URI"' in ids.content
    assert 'alert http any any -> any any (msg:"FSL XSS' in ids.content

def test_a_suppression_carries_a_deadline(client, ids):
    created = client.post_json("/api/rules/suppressions/", {"sid": 9000001}).json()

    assert created["expires_at"] > created["created_at"]
    assert created["restored_at"] is None

def test_a_suppression_lasts_as_long_as_was_asked(client, ids):
    from django.utils.dateparse import parse_datetime

    created = client.post_json(
        "/api/rules/suppressions/", {"sid": 9000001, "minutes": 7}
    ).json()

    lasts = parse_datetime(created["expires_at"]) - parse_datetime(created["created_at"])
    assert abs(lasts - timedelta(minutes=7)) < timedelta(seconds=5), lasts

def test_silencing_a_rule_that_does_not_exist_changes_nothing(client, ids):
    response = client.post_json("/api/rules/suppressions/", {"sid": 4242})

    assert response.status_code == 404
    assert not ids.applied
    assert client.get("/api/rules/suppressions/").json()["suppressions"] == []

def test_a_sid_that_is_not_a_number_is_rejected(client, ids):
    response = client.post_json("/api/rules/suppressions/", {"sid": "all of them"})

    assert response.status_code == 400
    assert not ids.applied

def test_a_rule_file_the_ids_refuses_is_not_recorded(client, ids):
    with patch("api.views.suricata.apply", side_effect=RuleApplyError("bad config")):
        response = client.post_json("/api/rules/suppressions/", {"sid": 9000001})

    assert response.status_code == 400
    assert client.get("/api/rules/suppressions/").json()["suppressions"] == []

def test_an_expired_suppression_puts_the_rule_back(client, ids):
    created = client.post_json(
        "/api/rules/suppressions/", {"sid": 9000001, "minutes": 30}
    ).json()
    assert "#alert" in ids.content

    from api.models import Suppression

    Suppression.objects.filter(pk=created["id"]).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    listed = client.get("/api/rules/suppressions/").json()

    assert listed["suppressions"] == [], "an expired suppression is still listed"
    assert [r["sid"] for r in listed["restored"]] == [9000001]
    assert ids.content == RULES, "the rule file did not come back byte for byte"

def test_a_live_suppression_is_not_lifted_early(client, ids):
    client.post_json("/api/rules/suppressions/", {"sid": 9000001, "minutes": 60})

    listed = client.get("/api/rules/suppressions/").json()

    assert [s["sid"] for s in listed["suppressions"]] == [9000001]
    assert listed["restored"] == []
    assert "#alert" in ids.content

def test_a_suppression_can_be_lifted_by_hand(client, ids):
    created = client.post_json("/api/rules/suppressions/", {"sid": 9000001}).json()

    response = client.post_json(f"/api/rules/suppressions/{created['id']}/restore/")

    assert response.status_code == 200
    assert response.json()["restored_at"] is not None
    assert ids.content == RULES

REWORDED = 'alert http any any -> any any (msg:"FSL SQLi attempt - URI, reworded"; sid:9000001; rev:1;)\n'

def refuses_a_duplicate_signature(ids):
    def apply(content, sensor, reload_command=None):
        active = [l for l in content.splitlines() if "sid:9000001" in l and not l.startswith("#")]
        if len(active) > 1:
            raise RuleApplyError(f'Duplicate signature "{active[-1]}"')
        ids.apply(content, sensor, reload_command)

    return patch("api.views.suricata.apply", apply)

def the_replacement_alone_carries_the_sid(content):
    from suppress import MARKER

    assert MARKER not in content
    assert [line for line in content.splitlines() if "sid:9000001" in line] == [REWORDED.strip()], (
        "the lift uncommented the silenced original beside the rule that replaced "
        "it: two active rules with one sid and rev, which suricata -T refuses as "
        "a duplicate signature on every try"
    )

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

def test_a_suppression_lifted_by_hand_after_its_rule_was_replaced_says_so(client, ids):
    created = client.post_json("/api/rules/suppressions/", {"sid": 9000001}).json()
    ids.content += REWORDED

    with refuses_a_duplicate_signature(ids):
        response = client.post_json(f"/api/rules/suppressions/{created['id']}/restore/")

    assert response.status_code == 200, response.content
    assert response.json()["restored_at"] is not None
    assert "superseded" in response.json()["detail"]
    the_replacement_alone_carries_the_sid(ids.content)

def test_a_suppression_that_cannot_be_lifted_stays_on_the_books(client, ids):
    created = client.post_json("/api/rules/suppressions/", {"sid": 9000001}).json()

    with patch("api.views.suricata.apply", side_effect=RuleApplyError("bad config")):
        response = client.post_json(f"/api/rules/suppressions/{created['id']}/restore/")

    assert response.status_code == 400
    assert [s["sid"] for s in client.get("/api/rules/suppressions/").json()["suppressions"]] == [9000001]
