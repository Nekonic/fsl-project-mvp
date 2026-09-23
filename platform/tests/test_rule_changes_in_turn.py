import threading
import time
from unittest.mock import patch

import pytest

from range.ports import Ran
from rules import suricata

pytestmark = pytest.mark.django_db(transaction=True)

TWO_RULES = (
    'alert http any any -> any any (msg:"one"; sid:9000901; rev:1;)\n'
    'alert http any any -> any any (msg:"two"; sid:9000902; rev:1;)\n'
)


class SlowSensor:
    def __init__(self, rules):
        self.rules = rules

    def runner(self, role, segment_id=""):
        return self

    def __call__(self, argv, stdin=None, timeout=60.0):
        if argv[:1] == ["cat"]:
            seen = self.rules
            time.sleep(0.3)
            return Ran(0, seen)
        if argv[:2] == ["sh", "-c"] and suricata.RULE_PATH in argv[-1]:
            self.rules = stdin
        return Ran(0, "")


def test_two_suppressions_at_once_both_take_effect(client):
    sensor = SlowSensor(TWO_RULES)

    def silence(sid):
        client.post_json("/api/rules/suppressions/", {"sid": sid, "minutes": 5})

    with patch("api.views.substrate", return_value=sensor):
        both = [threading.Thread(target=silence, args=(sid,)) for sid in (9000901, 9000902)]
        for thread in both:
            thread.start()
        for thread in both:
            thread.join()

    live = [line for line in sensor.rules.splitlines() if line.startswith("alert")]
    assert live == [], (
        f"two suppressions read the same rule file, each wrote back its own "
        f"edit, and the second erased the first: {live} is still live while "
        f"the suppression list says it is silenced"
    )
