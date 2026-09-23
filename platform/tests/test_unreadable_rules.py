from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from api.models import Suppression
from range.ports import Ran

pytestmark = pytest.mark.django_db

RULE = 'alert http any any -> any any (msg:"one"; sid:9000901; rev:1;)\n'


class Unreadable:
    def __init__(self):
        self.writes = []

    def runner(self, role, segment_id=""):
        return self

    def __call__(self, argv, stdin=None, timeout=60.0):
        if argv[:1] == ["cat"]:
            return Ran(1, "cat: can't open: Permission denied")
        if argv[:2] == ["sh", "-c"]:
            self.writes.append(stdin)
        return Ran(0, "")


def test_the_rules_endpoint_does_not_serve_an_error_as_the_rule_file(client):
    with patch("api.views.substrate", return_value=Unreadable()):
        response = client.get("/api/rules/")

    assert response.status_code == 503, (
        f"the sensor's cat failed and its error message was served as the rule "
        f"file ({response.status_code}); the editor would have applied it back"
    )


def test_a_suppression_is_not_recorded_as_lifted_when_the_rules_could_not_be_read(client):
    sensor = Unreadable()
    record = Suppression.objects.create(
        sid=9000901, original=RULE, reason="",
        expires_at=timezone.now() - timedelta(minutes=1),
    )

    with patch("api.views.substrate", return_value=sensor):
        response = client.get("/api/rules/suppressions/")

    record.refresh_from_db()
    assert record.restored_at is None, (
        "the rule file could not be read, the error text was edited as if it "
        "were rules, and the suppression was marked lifted while the rule "
        "stayed silenced"
    )
    assert response.status_code == 503
    assert sensor.writes == []
