from unittest.mock import patch

import pytest

from range.ports import Ran, RangeUnavailable
from rules.suricata import RuleApplyError

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("a_session_is_open")]

RELOAD = ("suricatasc", "-c", "reload-rules")
GOOD_RULE = 'alert http any any -> any any (msg:"FSL test"; sid:9000001; rev:1;)\n'

class Sensor:
    def __init__(self, replies=None, unreachable=False):
        self.calls = []
        self.replies = replies or {}
        self.unreachable = unreachable

    def __call__(self, argv, stdin=None, timeout=60.0):
        if self.unreachable:
            raise RangeUnavailable("fsl-suricata is not running")
        self.calls.append((argv, stdin))
        for needle, reply in self.replies.items():
            if needle in " ".join(argv):
                return reply
        return Ran(0, "")

def test_validate_endpoint_does_not_store_a_ruleset(client):
    from api.models import RuleSet

    with patch(
        "api.views.suricata.validate", return_value=Ran(0, "ok")
    ):
        response = client.post_json("/api/rules/validate/", {"content": GOOD_RULE})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert RuleSet.objects.count() == 0

    with patch("api.views.suricata.validate", return_value=Ran(1, "Error parsing signature")):
        refused = client.post_json("/api/rules/validate/", {"content": "x"})

    assert refused.status_code == 400
    assert "Error parsing signature" in refused.json()["output"]

def test_apply_endpoint_stores_and_marks_applied(client):
    from api.models import RuleSet

    with patch("api.views.suricata.apply") as applier, patch("api.views.suricata.current", return_value=""):
        response = client.post_json("/api/rules/apply/", {"content": GOOD_RULE})

    assert applier.call_args.args[0] == GOOD_RULE
    assert response.status_code == 200
    stored = RuleSet.objects.get()
    assert stored.content == GOOD_RULE
    assert stored.applied_at is not None

    with patch("api.views.suricata.apply", side_effect=RuleApplyError("bad rule")), \
            patch("api.views.suricata.current", return_value=""):
        refused = client.post_json("/api/rules/apply/", {"content": "x"})

    assert refused.status_code == 400
    assert "bad rule" in refused.json()["detail"]
    assert RuleSet.objects.count() == 1

def test_rules_endpoint_returns_current_file_content(client):
    with patch("api.views.suricata.current", return_value=GOOD_RULE):
        response = client.get("/api/rules/")

    assert response.status_code == 200
    assert response.json()["content"] == GOOD_RULE

def test_a_session_s_sensor_is_seeded_with_its_rule_set_and_loads_it():
    from rules import suricata

    sensor = Sensor(replies={"reload-rules": Ran(0, '{"message":"done","return":"OK"}')})
    suricata.seed(GOOD_RULE, sensor, RELOAD)

    written = [(argv, stdin) for argv, stdin in sensor.calls if argv[:2] == ["sh", "-c"]]
    assert written == [(["sh", "-c", f"mkdir -p /var/lib/suricata/rules && cat > {suricata.RULE_PATH}"], GOOD_RULE)], (
        "a fresh sensor has no rules directory; the seed must make it before writing"
    )
    assert sensor.calls[-1][0] == list(RELOAD)

def test_a_sensor_that_does_not_load_its_seed_fails_the_open():
    from rules import suricata

    sensor = Sensor(replies={"reload-rules": Ran(1, "Error: Closed")})

    with pytest.raises(RuleApplyError, match="starting rule set"):
        suricata.seed(GOOD_RULE, sensor, RELOAD)
