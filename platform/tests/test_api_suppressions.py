"""Turning a verdict into a rule change, and taking it back on a deadline.

Every console lets an analyst record "false positive"; none of them change the
rule that produced it, because recording verdicts and editing detections are
different teams with different tools. The range owns both, so here they are the
same call - and every suppression is a false-negative bet, so it expires.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from rules.suricata import RuleApplyError

pytestmark = pytest.mark.django_db

RULES = (
    '# FSL MVP baseline rules.\n\n'
    'alert http any any -> any any (msg:"FSL SQLi attempt - URI"; sid:9000001; rev:1;)\n\n'
    'alert http any any -> any any (msg:"FSL XSS attempt"; sid:9000003; rev:1;)\n'
)


class Suricata:
    """A rule file that remembers what was written to it."""

    def __init__(self, content=RULES):
        self.content = content
        self.applied = []

    def current(self):
        return self.content

    def apply(self, content):
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
    # The other rule is untouched.
    assert 'alert http any any -> any any (msg:"FSL XSS' in ids.content


def test_a_suppression_carries_a_deadline(client, ids):
    created = client.post_json("/api/rules/suppressions/", {"sid": 9000001}).json()

    assert created["expires_at"] > created["created_at"]
    assert created["restored_at"] is None


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
    # Otherwise the platform believes a rule is off that is still firing.
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


def test_a_suppression_that_cannot_be_lifted_stays_on_the_books(client, ids):
    # A rule that is off with nothing saying so is the worst of both.
    created = client.post_json("/api/rules/suppressions/", {"sid": 9000001}).json()

    with patch("api.views.suricata.apply", side_effect=RuleApplyError("bad config")):
        response = client.post_json(f"/api/rules/suppressions/{created['id']}/restore/")

    assert response.status_code == 400
    assert [s["sid"] for s in client.get("/api/rules/suppressions/").json()["suppressions"]] == [9000001]
