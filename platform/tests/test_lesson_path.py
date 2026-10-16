from unittest.mock import patch

import pytest

import wargames
from range.ports import Ran

pytestmark = pytest.mark.django_db

KOREAN = "서울 맛집 추천"

def test_the_new_benign_cases_are_ordinary_requests_and_the_comment_has_the_xss_comment_s_shape():
    korean = wargames.find_case("board", "board-normal-search-korean")
    comment = wargames.find_case("board", "board-normal-comment")
    xss = wargames.find_case("board", "board-xss-img-onerror-in-comment")

    assert not korean["malicious"] and korean["request"]["params"] == {"q": KOREAN}
    assert not comment["malicious"]
    assert {key: value for key, value in comment["request"].items() if key != "json"} == \
        {key: value for key, value in xss["request"].items() if key != "json"}
    assert set(comment["request"]["json"]) == set(xss["request"]["json"])

def test_rule_validation_reports_suricata_s_error_lines_from_the_sensor_that_printed_them(client, settings):
    settings.FSL_EXTRA_SENSORS = (("estate-sensor", "/var/lib/suricata/rules/local.rules", ("reload",)),)
    quiet = "Info: conf-yaml-loader: Including configuration file conf.d/fsl.yaml.\n"
    loud = ("Info: suricata: This is Suricata version 7.0.8 RELEASE running in SYSTEM mode\n"
            "Error: detect-parse: unknown rule keyword 'contnet'.\n"
            "Error: detect: error parsing signature \"alert http any any -> any any (contnet:\\\"x\\\"; sid:1;)\" "
            "from file /dev/stdin at line 1\n")

    def runner(adapter, role, segment_id=""):
        return lambda argv, stdin=None, timeout=60.0: Ran(1, quiet if role == "sensor" else loud)

    with patch("range.docker.Docker.runner", runner):
        checked = client.post_json("/api/rules/validate/", {"content": "alert http any any -> any any (contnet:\"x\"; sid:1;)"})

    assert checked.status_code == 400
    assert checked.json()["errors"] == [
        "Error: detect-parse: unknown rule keyword 'contnet'.",
        "Error: detect: error parsing signature \"alert http any any -> any any (contnet:\\\"x\\\"; sid:1;)\" "
        "from file /dev/stdin at line 1",
    ]
    assert "contnet" in checked.json()["output"], "the output shown is the one that names the error"
