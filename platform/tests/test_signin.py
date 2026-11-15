import json
import re
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import URLPattern, get_resolver

from api import signin
from tests.conftest import ApiClient

pytestmark = pytest.mark.django_db

OPEN = {"/login/", "/signup/", "/api/auth/", "/api/auth/login/", "/api/auth/signup/", "/auth-check/"}
SITE_PROXY = "site-proxy/"


def every_path():
    for pattern in get_resolver().url_patterns:
        assert isinstance(pattern, URLPattern)
        route = str(pattern.pattern)
        if route.startswith(SITE_PROXY):
            continue
        yield "/" + re.sub(r"<int:[^>]+>", "1", re.sub(r"<str:[^>]+>", "x", route))


GUARDED = sorted(path for path in every_path() if path not in OPEN)


def signed_in_client(**options):
    client = ApiClient(**options)
    token = client.get("/api/auth/").json()["csrf_token"]
    answer = client.post("/api/auth/login/", json.dumps({"username": "admin", "password": "123456"}),
                         content_type="application/json", HTTP_X_CSRFTOKEN=token)
    assert answer.status_code == 200, answer.content
    return client, answer


@pytest.mark.parametrize("path", GUARDED)
def test_every_page_and_endpoint_refuses_a_caller_who_has_not_signed_in(path):
    for answer in (Client().get(path), Client().post(path, "{}", content_type="application/json")):
        method = answer.request["REQUEST_METHOD"]
        if path.startswith("/api/"):
            assert answer.status_code == 401, f"{method} {path} answered {answer.status_code}"
            assert "sign in" in answer.json()["detail"]
        else:
            assert answer.status_code == 302 and answer["Location"].startswith("/login/?next="), (
                f"{method} {path} answered {answer.status_code}"
            )


def test_the_first_start_holds_the_admin_account_with_the_mandated_password():
    admin = get_user_model().objects.get(username="admin")

    assert admin.check_password("123456")


def test_signing_in_over_rest_opens_the_api_and_signing_out_closes_it():
    client, answer = signed_in_client()

    assert answer.json()["user"] == "admin" and answer.json()["csrf_token"]
    assert client.get("/api/sessions/").status_code == 200
    assert client.get("/api/auth/").json()["user"] == "admin"
    client.post("/api/auth/logout/", "{}", content_type="application/json")
    assert client.get("/api/sessions/").status_code == 401


def test_a_wrong_password_is_refused_and_signs_nobody_in():
    client = Client()
    answer = client.post("/api/auth/login/", json.dumps({"username": "admin", "password": "wrong"}),
                         content_type="application/json")

    assert answer.status_code == 401
    assert client.get("/api/sessions/").status_code == 401


def test_the_session_cookie_is_out_of_reach_of_page_script():
    _, answer = signed_in_client()
    cookie = answer.cookies["cr_session"]

    assert cookie["httponly"] is True and cookie["samesite"] == "Lax"
    assert "csrftoken" not in answer.cookies, "a CSRF cookie would hand the token to script on :8002"


@pytest.mark.parametrize("origin", ["http://testserver:8002", "http://attacker.example"])
def test_a_cross_origin_post_without_the_csrf_token_is_refused(origin):
    client, _ = signed_in_client(enforce_csrf_checks=True)
    client.defaults.pop("HTTP_X_CSRFTOKEN", None)

    with patch("api.views.suricata.apply") as applied:
        answer = client.post("/api/rules/apply/", json.dumps({"content": ""}),
                             content_type="application/json", HTTP_ORIGIN=origin)

    assert answer.status_code == 403
    applied.assert_not_called()


def test_a_same_origin_post_needs_the_csrf_token_too():
    client, signed = signed_in_client(enforce_csrf_checks=True)

    refused = client.post("/api/auth/logout/", "{}", content_type="application/json")
    taken = client.post("/api/auth/logout/", "{}", content_type="application/json",
                        HTTP_X_CSRFTOKEN=signed.json()["csrf_token"])

    assert refused.status_code == 403 and "CSRF" in refused.json()["detail"]
    assert taken.status_code == 200 and taken.json()["user"] is None


def test_no_answer_grants_another_origin_a_read():
    client, _ = signed_in_client()
    answers = [
        client.get("/api/sessions/", HTTP_ORIGIN="http://testserver:8002"),
        client.options("/api/sessions/", HTTP_ORIGIN="http://testserver:8002",
                       HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST"),
        client.get("/api/auth/", HTTP_ORIGIN="http://testserver:8002"),
    ]

    for answer in answers:
        assert not [name for name in answer.headers if name.lower().startswith("access-control-")]


def test_the_front_s_check_answers_401_until_signed_in():
    assert Client().get("/auth-check/").status_code == 401
    client, _ = signed_in_client()

    assert client.get("/auth-check/").status_code == 204


def test_the_login_page_opens_without_a_session_and_posts_to_the_login_api():
    page = Client().get("/login/").content.decode()

    assert 'id="sign-in"' in page and 'type="password"' in page
    assert 'post("/api/auth/login/"' in page
    assert 'id="sign-out"' not in page

