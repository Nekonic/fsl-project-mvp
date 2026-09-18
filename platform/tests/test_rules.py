import subprocess
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from rules.suricata import RuleApplyError, ValidationOutcome

pytestmark = pytest.mark.django_db

GOOD_RULE = 'alert http any any -> any any (msg:"FSL test"; sid:9000001; rev:1;)\n'


@pytest.fixture
def client():
    return APIClient()


def completed(returncode, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=["docker"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_validate_returns_ok_when_suricata_test_succeeds():
    from rules import suricata

    with patch.object(suricata, "_write_candidate") as write, patch.object(
        suricata,
        "_run",
        return_value=completed(0, "Configuration provided was successfully loaded"),
    ):
        outcome = suricata.validate(GOOD_RULE)

    assert outcome.ok is True
    assert "successfully loaded" in outcome.output
    write.assert_called_once_with(GOOD_RULE)


def test_validate_returns_failure_output_verbatim():
    from rules import suricata

    with patch.object(suricata, "_write_candidate"), patch.object(
        suricata, "_run", return_value=completed(1, "", "Error parsing signature")
    ):
        outcome = suricata.validate("garbage")

    assert outcome.ok is False
    assert "Error parsing signature" in outcome.output


def test_apply_refuses_content_that_fails_validation():
    from rules import suricata

    with patch.object(
        suricata, "validate", return_value=ValidationOutcome(ok=False, output="bad")
    ), patch.object(suricata, "_write_rules") as write:
        with pytest.raises(RuleApplyError, match="bad"):
            suricata.apply("garbage")

    write.assert_not_called()


def test_apply_writes_then_reloads():
    from rules import suricata

    with patch.object(
        suricata, "validate", return_value=ValidationOutcome(ok=True, output="ok")
    ), patch.object(suricata, "_read_rules", return_value="OLD\n"), patch.object(
        suricata, "_write_rules"
    ) as write, patch.object(
        suricata, "_run", return_value=completed(0)
    ) as run:
        suricata.apply(GOOD_RULE)

    write.assert_called_once_with(GOOD_RULE)
    assert any("kill" in str(call) for call in run.call_args_list)


def test_apply_restores_previous_rules_when_reload_fails():
    from rules import suricata

    with patch.object(
        suricata, "validate", return_value=ValidationOutcome(ok=True, output="ok")
    ), patch.object(suricata, "_read_rules", return_value="OLD\n"), patch.object(
        suricata, "_write_rules"
    ) as write, patch.object(
        suricata, "_run", return_value=completed(1, "", "no such container")
    ):
        with pytest.raises(RuleApplyError, match="no such container"):
            suricata.apply(GOOD_RULE)

    assert write.call_args_list[-1].args[0] == "OLD\n"


def test_validate_endpoint_does_not_store_a_ruleset(client):
    from api.models import RuleSet

    with patch(
        "api.views.suricata.validate", return_value=ValidationOutcome(ok=True, output="ok")
    ):
        response = client.post("/api/rules/validate/", {"content": GOOD_RULE}, format="json")

    assert response.status_code == 200
    assert response.data["ok"] is True
    assert RuleSet.objects.count() == 0


def test_validate_endpoint_reports_failure_as_400_with_output(client):
    with patch(
        "api.views.suricata.validate",
        return_value=ValidationOutcome(ok=False, output="Error parsing signature"),
    ):
        response = client.post("/api/rules/validate/", {"content": "x"}, format="json")

    assert response.status_code == 400
    assert "Error parsing signature" in response.data["output"]


def test_apply_endpoint_stores_and_marks_applied(client):
    from api.models import RuleSet

    with patch("api.views.suricata.apply") as applier:
        response = client.post("/api/rules/apply/", {"content": GOOD_RULE}, format="json")

    applier.assert_called_once_with(GOOD_RULE)
    assert response.status_code == 200
    stored = RuleSet.objects.get()
    assert stored.content == GOOD_RULE
    assert stored.applied_at is not None


def test_apply_endpoint_returns_400_and_stores_nothing_on_failure(client):
    from api.models import RuleSet

    with patch("api.views.suricata.apply", side_effect=RuleApplyError("bad rule")):
        response = client.post("/api/rules/apply/", {"content": "x"}, format="json")

    assert response.status_code == 400
    assert "bad rule" in response.data["detail"]
    assert RuleSet.objects.count() == 0


def test_rules_endpoint_returns_current_file_content(client):
    with patch("api.views.suricata.current", return_value=GOOD_RULE):
        response = client.get("/api/rules/")

    assert response.status_code == 200
    assert response.data["content"] == GOOD_RULE
