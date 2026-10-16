from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("a_session_is_open")]

RULE = "alert http any any -> any any (msg:\"x\"; sid:9000001;)\n"


@pytest.mark.parametrize("body", [{}, {"content": None}, {"content": 7}, {"content": ["a"]}])
def test_applying_without_a_rule_file_leaves_the_sensor_alone(client, body):
    with patch("api.views.suricata.apply") as applied:
        response = client.post_json("/api/rules/apply/", body)

    assert response.status_code == 400, (
        f"{body} was taken as an empty rule file: the sensor was reloaded with "
        f"nothing and every attack after it scores as a miss"
    )
    applied.assert_not_called()


@pytest.mark.parametrize("minutes", ["x", -5, 0, 10**9, "nan", "inf"])
def test_a_suppression_length_outside_what_makes_sense_is_refused(client, minutes):
    with patch("api.views.suricata.current", return_value=RULE) as read:
        response = client.post_json(
            "/api/rules/suppressions/", {"sid": 9000001, "minutes": minutes}
        )

    assert response.status_code == 400, (
        f"minutes={minutes!r} answered {response.status_code}: a suppression "
        f"that never ends, or ends before it starts, is not a suppression"
    )
    read.assert_not_called()


def a_case(**overrides):
    return {
        "case_id": "0b6f8d64-1111-4111-8111-111111111111",
        "name": "benign-browse",
        "malicious": False,
        "correlation": "marker",
        "started_at": "2026-09-24T10:00:00Z",
        "ended_at": "2026-09-24T10:00:01Z",
        **overrides,
    }


@pytest.fixture
def session_id(client):
    return client.post_json("/api/sessions/", {}).json()["id"]


def record(client, session_id, case):
    with patch("api.views._observe_objectives", return_value={"achieved": 0}):
        return client.post_json(f"/api/sessions/{session_id}/cases/", case)


@pytest.mark.parametrize("given", ["false", "true", 0, 1, None, "no"])
def test_whether_a_case_was_an_attack_is_a_boolean_and_nothing_else(client, session_id, given):
    response = record(client, session_id, a_case(malicious=given))

    assert response.status_code == 400, (
        f"malicious={given!r} was stored as {bool(given)}: a benign case posted "
        f"as \"false\" became an attack, which turns its TN into a FN - the same "
        f"harm as deleting a benign case"
    )


@pytest.mark.parametrize("times", [
    {"started_at": "not-a-date"},
    {"started_at": "2026-13-40T00:00:00Z"},
    {"ended_at": "2026-09-24T10:00:01"},
    {"started_at": 1727172000},
    {"started_at": "2026-09-24T10:00:05Z", "ended_at": "2026-09-24T10:00:00Z"},
])
def test_a_case_window_that_is_not_two_ordered_instants_is_refused(client, session_id, times):
    response = record(client, session_id, a_case(**times))

    assert response.status_code == 400, (times, response.status_code)


@pytest.mark.parametrize("given", ["999.1.1.1", "localhost", 42])
def test_a_source_that_is_not_an_address_is_refused(client, session_id, given):
    response = record(client, session_id, a_case(source_ip=given, correlation="window"))

    assert response.status_code == 400, (given, response.status_code)


def test_recording_the_same_case_twice_is_a_conflict(client, session_id):
    assert record(client, session_id, a_case()).status_code == 201

    again = record(client, session_id, a_case())

    assert again.status_code == 409, (
        f"the second copy of a case answered {again.status_code}; a retry after "
        f"a timeout is ordinary and deserves to be told the case is already there"
    )


@pytest.mark.parametrize("given", [7, True, ["SQL"], {"text": "SQL"}])
def test_what_a_case_should_be_found_by_is_text_or_nothing(client, session_id, given):
    response = record(client, session_id, a_case(expect=given))

    assert response.status_code == 400, (
        f"expect={given!r} was accepted: it is matched against alert signatures "
        f"as text, so anything else would be judged on its repr"
    )
    assert "expect" in response.json()


@pytest.mark.parametrize("posted, stored", [
    ({"expect": "SQL"}, "SQL"), ({"expect": ""}, ""), ({}, ""), ({"expect": None}, ""),
])
def test_what_a_case_should_be_found_by_is_recorded_as_given_or_as_none(client, session_id, posted, stored):
    response = record(client, session_id, a_case(**posted))

    assert response.status_code == 201, response.content
    assert response.json()["expect"] == stored, (
        "a case posted with no expectation was stored as null, which means "
        "recorded before expectations were kept, so its score is judged by the "
        "case file as it is now"
    )


@pytest.mark.parametrize("given", [
    0, False, 123, {}, ["c0ffee"], "a\r\nb", "a\r\nX-Other: 1", "two words",
    "tab\tbetween", "nul\x00", "zero​width", " ",
])
def test_a_label_that_is_not_one_marker_is_refused_before_the_proxy_stamps_it(client, given):
    with patch("api.views.attacker.set_label") as labelled:
        response = client.post_json("/api/attacker/label/", {"case_id": given})

    assert response.status_code == 400, (
        f"case_id={given!r} answered {response.status_code}; the proxy puts the "
        f"label into the X-FSL-Case header of every request the terminal sends, "
        f"so a line break there writes headers of the caller's choosing"
    )
    assert response.json()["detail"]
    labelled.assert_not_called()


@pytest.mark.parametrize("given, stamped", [
    (None, (None, "")), ("", (None, "")),
    ("44444444-4444-4444-8444-444444444444", ("44444444-4444-4444-8444-444444444444",)),
    ("sqli-login-bypass", ("sqli-login-bypass",)),
])
def test_a_label_can_still_be_cleared_and_a_marker_is_stamped_as_given(client, given, stamped):
    with patch("api.views.attacker.set_label") as labelled:
        response = client.post_json("/api/attacker/label/", {"case_id": given})

    assert response.status_code == 200
    assert labelled.call_args.args[0] in stamped


