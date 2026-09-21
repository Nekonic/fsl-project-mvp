from unittest.mock import patch

import pytest

from range.ports import Ran, RangeUnavailable
from rules.suricata import RuleApplyError, ValidationOutcome

pytestmark = pytest.mark.django_db

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

def sensor_of(substrate):
    return substrate.runner.call_args.args[0]

def test_the_endpoint_asks_the_substrate_for_the_sensor_and_nothing_else():
    from range.docker import Docker

    substrate = Docker(hosts={"sensor": "fsl-suricata"})
    run = substrate.runner("sensor")

    with patch("range.docker.subprocess.run") as ran:
        ran.return_value.returncode = 0
        ran.return_value.stdout = "ok"
        ran.return_value.stderr = ""
        run(["suricata", "-T", "-S", "/x"])

    argv = ran.call_args.args[0]
    assert argv[:3] == ["docker", "exec", "fsl-suricata"], argv
    assert argv[3:] == ["suricata", "-T", "-S", "/x"], argv

def test_writing_through_the_substrate_opens_stdin():
    from range.docker import Docker

    run = Docker(hosts={"sensor": "fsl-suricata"}).runner("sensor")

    with patch("range.docker.subprocess.run") as ran:
        ran.return_value.returncode = 0
        ran.return_value.stdout = ""
        ran.return_value.stderr = ""
        run(["sh", "-c", "cat > /x"], stdin=GOOD_RULE)

    assert "-i" in ran.call_args.args[0], "docker exec without -i discards stdin"
    assert ran.call_args.kwargs["input"] == GOOD_RULE

def test_a_missing_sensor_is_unavailable_not_a_failed_command():
    from range.docker import Docker

    run = Docker(hosts={"sensor": "fsl-suricata"}).runner("sensor")

    with patch("range.docker.subprocess.run") as ran:
        ran.return_value.returncode = 1
        ran.return_value.stdout = ""
        ran.return_value.stderr = "Error: No such container: fsl-suricata"
        with pytest.raises(RangeUnavailable):
            run(["cat", "/x"])

def test_a_role_no_host_fills_is_refused_before_anything_runs():
    from range.docker import Docker

    with pytest.raises(RangeUnavailable, match="sensor"):
        Docker(hosts={}).runner("sensor")

def test_the_rule_paths_are_the_sensors_own():
    from rules import suricata

    sensor = Sensor()
    suricata.apply(GOOD_RULE, sensor)

    written = [argv for argv, stdin in sensor.calls if stdin is not None]
    assert all("/var/lib/suricata/rules/" in " ".join(a) for a in written), written

def test_validate_endpoint_does_not_store_a_ruleset(client):
    from api.models import RuleSet

    with patch(
        "api.views.suricata.validate", return_value=ValidationOutcome(ok=True, output="ok")
    ):
        response = client.post_json("/api/rules/validate/", {"content": GOOD_RULE})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert RuleSet.objects.count() == 0

def test_validate_endpoint_reports_failure_as_400_with_output(client):
    with patch(
        "api.views.suricata.validate",
        return_value=ValidationOutcome(ok=False, output="Error parsing signature"),
    ):
        response = client.post_json("/api/rules/validate/", {"content": "x"})

    assert response.status_code == 400
    assert "Error parsing signature" in response.json()["output"]

def test_apply_endpoint_stores_and_marks_applied(client):
    from api.models import RuleSet

    with patch("api.views.suricata.apply") as applier:
        response = client.post_json("/api/rules/apply/", {"content": GOOD_RULE})

    assert applier.call_args.args[0] == GOOD_RULE
    assert response.status_code == 200
    stored = RuleSet.objects.get()
    assert stored.content == GOOD_RULE
    assert stored.applied_at is not None

def test_apply_endpoint_returns_400_and_stores_nothing_on_failure(client):
    from api.models import RuleSet

    with patch("api.views.suricata.apply", side_effect=RuleApplyError("bad rule")):
        response = client.post_json("/api/rules/apply/", {"content": "x"})

    assert response.status_code == 400
    assert "bad rule" in response.json()["detail"]
    assert RuleSet.objects.count() == 0

def test_rules_endpoint_returns_current_file_content(client):
    with patch("api.views.suricata.current", return_value=GOOD_RULE):
        response = client.get("/api/rules/")

    assert response.status_code == 200
    assert response.json()["content"] == GOOD_RULE
