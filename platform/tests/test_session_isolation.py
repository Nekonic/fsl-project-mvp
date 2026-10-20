import pathlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import override_settings

from api import views
from api.models import Session
from range import declared
from range.ports import RangeUnavailable
from tests.test_lesson_api import TwoSlots

ROOT = pathlib.Path(__file__).resolve().parents[2]


class Sensors:
    def __init__(self, rules="alert http any any -> any any (msg:\"x\"; sid:9000001; rev:1;)\n"):
        self.rules = {}
        self.default = rules
        self.ran_in = []

    def install(self):
        sensors = self

        def runner(adapter, role, segment_id=""):
            def run(argv, stdin=None, timeout=60.0):
                sensors.ran_in.append((role, adapter.session))
                return type("Ran", (), {"ok": True, "output": "", "exit_code": 0})()
            return run

        stand = SimpleNamespace(runner=lambda: runner)
        return patch("api.views.substrate", lambda: TwoSlots(stand))


def opened_sessions(n):
    return [Session.objects.create(scenario="board", baseline=[], slot=number) for number in range(1, n + 1)]


@pytest.mark.django_db
def test_rules_act_on_the_sensor_of_the_session_asked_for(client):
    older, _ = opened_sessions(2)
    sensors = Sensors()

    with sensors.install(), patch("api.views.suricata.apply") as applied, \
            patch("api.views.suricata.current", return_value=sensors.default) as read:
        client.get(f"/api/rules/?session={older.pk}")
        client.post_json("/api/rules/apply/", {"content": sensors.default, "session": older.pk})

    read.call_args.args[0](["true"])
    applied.call_args.args[1](["true"])
    assert sensors.ran_in[-2:] == [("sensor", "slot-1"), ("estate-sensor", "slot-1")], (
        "a rule written for one session's sensor reached the newest session's"
    )


@pytest.mark.django_db
def test_a_suppression_is_lifted_on_the_sensor_it_was_set_on(client):
    older, _ = opened_sessions(2)
    rule = 'alert http any any -> any any (msg:"x"; sid:9000901; rev:1;)\n'
    sensors = Sensors()

    with sensors.install(), patch("api.views.suricata.current", return_value=rule), \
            patch("api.views.suricata.apply") as applied:
        made = client.post_json(
            "/api/rules/suppressions/", {"sid": 9000901, "session": older.pk}
        )
        from api.models import Suppression
        record = Suppression.objects.get()
        with patch("api.views.suricata.current", return_value="") as reread:
            client.post_json(f"/api/rules/suppressions/{record.pk}/restore/")

    assert made.status_code == 201, made.content
    assert record.session_id == older.pk
    reread.call_args.args[0](["true"])
    assert sensors.ran_in == [("sensor", "slot-1")], (
        "the expiry restored the rule on whichever sensor was newest"
    )


@pytest.mark.django_db
def test_the_red_console_s_calls_act_on_its_own_session(client):
    older, _ = opened_sessions(2)
    sensors = Sensors()

    with sensors.install():
        labelled = client.post_json(
            "/api/attacker/label/", {"case_id": "x", "session": older.pk}
        )

    assert labelled.status_code == 200, labelled.content
    assert sensors.ran_in == [("proxy", "slot-1")]
    assert client.post_json("/api/attacker/label/", {"case_id": "x", "session": "nine"}).status_code == 400
    assert client.post_json("/api/attacker/label/", {"case_id": "x", "session": 999}).status_code == 404


@pytest.mark.django_db
def test_on_openstack_the_waf_terminal_is_an_ssh_shell_on_the_waf_vm(client):
    with override_settings(WAF_SESSION_TERMINAL_URL=""):
        session, = opened_sessions(1)
        assert client.get(f"/api/sessions/{session.pk}/").json()["waf_terminal"] == "/vm-terminal/waf/"

    assert "ttyd -W -a -b /vm-terminal/waf -t disableResizeOverlay=true -i 127.0.0.1 -p 7692 /app/vm-terminal.sh fsl-waf" in (
        ROOT / "platform/entrypoint.sh").read_text()
    assert "mgmt" in declared.read().hosts["fsl-waf"].segments
    shell = (ROOT / "platform/vm-terminal.sh").read_text()
    assert 'if seg.id == "mgmt"' in shell and '"ubuntu@${addr}"' in shell and '"kali@${addr}"' in shell, (
        "the shell is the ssh user the platform tunes the WAF as, on the VM's management address"
    )
    assert "StrictHostKeyChecking=accept-new" in shell and '-o HostKeyAlias=$alias' in shell, (
        "a rebuilt server is a new key under a new alias, so the terminal neither warns nor stops checking"
    )

@pytest.mark.django_db
def test_the_attacker_box_asked_for_no_session_is_the_newest_one(client):
    Session.objects.create(scenario="board", baseline=[])
    newest = Session.objects.create(scenario="board", baseline=[], ended_at="2026-10-10T00:00:00Z")
    asked = []

    def standing(session=None):
        asked.append(session.pk)
        raise RangeUnavailable("stand-in")

    with patch("api.views._standing", standing):
        client.get("/api/attacker/")

    assert asked == [newest.pk], (
        "the console's box and the shell the acceptance suite drives were two "
        "different sessions' attacker boxes"
    )


@pytest.mark.django_db
def test_a_suppression_on_a_session_whose_close_rebuilt_the_range_is_lifted_without_the_sensors(client):
    from django.utils import timezone

    from api.models import Suppression

    closed = Session.objects.create(scenario="board", baseline=[], ended_at=timezone.now())
    record = Suppression.objects.create(
        session=closed, sid=9000004, original="alert x", expires_at=timezone.now(),
    )

    class Rebuilding:
        def rebuild_slot(self):
            return []

        def runner(self, role, segment_id=""):
            raise RangeUnavailable(f"{role} is rebuilding")

    with patch("api.views._range", lambda session=None: Rebuilding()):
        restored = client.post_json(f"/api/rules/suppressions/{record.pk}/restore/")

    assert restored.status_code == 200, restored.content
    assert Suppression.objects.get(pk=record.pk).restored_at is not None, (
        "on openstack the close rebuilds every sensor from its image, so a "
        "restore sent while the sensors are down stayed in force and every "
        "later session was refused as off baseline"
    )

@pytest.mark.django_db
def test_a_suppression_on_an_open_session_is_not_dropped_when_its_sensor_is_down(client):
    from django.utils import timezone

    from api.models import Suppression

    live = Session.objects.create(scenario="board", baseline=[])
    record = Suppression.objects.create(
        session=live, sid=9000004, original="alert x", expires_at=timezone.now(),
    )

    with patch("api.views.suricata.current", side_effect=RangeUnavailable("no sensor")):
        restored = client.post_json(f"/api/rules/suppressions/{record.pk}/restore/")

    assert restored.status_code == 503
    assert Suppression.objects.get(pk=record.pk).restored_at is None


@pytest.mark.django_db
def test_a_write_naming_no_session_goes_to_the_newest_open_one(client):
    from django.utils import timezone

    Session.objects.create(scenario="board", baseline=[], slot=2)
    Session.objects.create(scenario="board", baseline=[], slot=1, ended_at=timezone.now())
    sensors = Sensors()

    with sensors.install():
        client.post_json("/api/attacker/label/", {"case_id": "x"})

    assert sensors.ran_in == [("proxy", "slot-2")], (
        "a write naming no session went to a closed session's slot"
    )


@pytest.mark.django_db
def test_a_write_with_no_session_open_is_refused(client):
    from django.utils import timezone

    Session.objects.create(scenario="board", baseline=[], ended_at=timezone.now())

    with Sensors().install():
        answer = client.post_json("/api/rules/apply/", {"content": ""})

    assert answer.status_code == 409


@pytest.mark.django_db
def test_a_write_to_a_closed_session_is_refused(client):
    from django.utils import timezone

    closed = Session.objects.create(scenario="board", baseline=[], ended_at=timezone.now())

    for path, body in (("/api/attacker/label/", {"case_id": "x"}),
                       ("/api/attacker/origin/", {"origin": ""}),
                       ("/api/rules/suppressions/", {"sid": 9000001}),
                       ("/api/rules/apply/", {"content": ""}),
                       ("/api/range/canary/", {})):
        answer = client.post_json(path, dict(body, session=closed.pk))
        assert answer.status_code == 409, (path, answer.content)
