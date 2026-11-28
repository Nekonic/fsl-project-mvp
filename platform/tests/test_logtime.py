import logging

from django.conf import settings
from django.utils.module_loading import import_string


def test_a_platform_log_line_carries_the_time_in_utc9_while_the_store_keeps_utc():
    formatting = settings.LOGGING["formatters"]["utc9"]
    formatter = import_string(formatting["()"])(formatting["format"])
    record = logging.LogRecord("training.round.lifecycle", logging.WARNING, __file__, 1, "round %s did not start",
                               (7,), None)
    record.created, record.msecs = 1795811625.25, 250.0

    assert formatter.format(record) == ("2026-11-28T05:33:45.250+09:00 WARNING training.round.lifecycle "
                                        "round 7 did not start")
    assert settings.USE_TZ and settings.TIME_ZONE == "UTC"
