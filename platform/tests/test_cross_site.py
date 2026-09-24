from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db

RULES = {"content": "alert http any any -> any any (msg:\"x\"; sid:9000901;)\n"}


@pytest.mark.parametrize("headers", [
    {"HTTP_ORIGIN": "http://attacker.example"},
    {"HTTP_ORIGIN": "http://localhost:8080"},
    {"HTTP_SEC_FETCH_SITE": "cross-site"},
    {"HTTP_SEC_FETCH_SITE": "same-site"},
])
def test_another_page_cannot_change_the_rules_through_the_operator_s_browser(client, headers):
    with patch("api.views.suricata.apply") as applied:
        response = client.post("/api/rules/apply/", RULES, content_type="application/json", **headers)

    assert response.status_code == 403, (
        f"{headers} changed the detector. The target on :8080 is the same site "
        f"as the judge on :8000, and making the target run script is what the "
        f"red team is scored on"
    )
    applied.assert_not_called()


REBOUND = {
    "HTTP_HOST": "rebind.attacker.example:8000",
    "HTTP_ORIGIN": "http://rebind.attacker.example:8000",
    "HTTP_SEC_FETCH_SITE": "same-origin",
}


def test_a_page_whose_name_was_rebound_to_the_platform_cannot_change_the_rules(client):
    with patch("api.views.suricata.apply") as applied:
        response = client.post("/api/rules/apply/", RULES, content_type="application/json", **REBOUND)

    assert 400 <= response.status_code < 500, (
        f"{response.status_code}: a page from another name, re-resolved to "
        f"127.0.0.1, sends an Origin equal to its own Host, and the platform "
        f"took that Host as its own origin"
    )
    applied.assert_not_called()


def test_a_page_whose_name_was_rebound_to_the_platform_cannot_read_it(client):
    with patch("api.views.suricata.current", return_value=RULES["content"]):
        response = client.get("/api/rules/", **REBOUND)

    assert 400 <= response.status_code < 500, (
        "the rebound page read the sensor's rules through the operator's browser"
    )


def test_a_form_post_cannot_reach_a_json_endpoint(client):
    with patch("api.views.suricata.apply") as applied:
        response = client.post(
            "/api/rules/apply/", '{"content": ""}', content_type="text/plain",
        )

    assert response.status_code == 415, (
        "a text/plain POST needs no preflight, so any page could send one; the "
        "body was parsed as JSON regardless of what it said it was"
    )
    applied.assert_not_called()


def test_the_console_s_own_requests_still_go_through(client):
    with patch("api.views.suricata.apply"):
        response = client.post(
            "/api/rules/apply/", RULES, content_type="application/json",
            HTTP_ORIGIN="http://testserver", HTTP_SEC_FETCH_SITE="same-origin",
        )

    assert response.status_code == 200, response.content


def test_a_bodiless_post_from_the_console_still_goes_through(client):
    session_id = client.post_json("/api/sessions/", {}).json()["id"]

    with patch("api.views.elastic.fetch", return_value=([], None)):
        response = client.generic(
            "POST", f"/api/sessions/{session_id}/ingest/", b"", HTTP_ORIGIN="http://testserver",
        )

    assert response.status_code == 200, response.content


def test_no_page_of_the_platform_can_be_framed(client):
    assert client.get("/").headers.get("X-Frame-Options") == "DENY"
