import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from tests.conftest import CALLER, PASSWORD
from tests.shape import refused
from users import accounts as signin
from users import permissions as users

STRONG = "violet-harbour-1187"


def sign_in(browser, username, password=PASSWORD):
    return browser.post("/api/auth/login/", {"username": username, "password": password}, format="json")


def sign_up(browser, username, password=STRONG):
    return browser.post("/api/auth/signup/", {"username": username, "password": password}, format="json")


def test_the_csrf_route_sets_the_cookie_the_console_reads(browser):
    answer = browser.get("/api/auth/csrf/")

    assert answer.status_code == 200 and answer.json() == {"ok": True}
    assert answer.cookies["cr_csrf"].value and not answer.cookies["cr_csrf"]["httponly"]


def test_signing_in_opens_a_session_that_me_reports(browser, learner):
    answer = sign_in(browser, "learner")

    assert answer.status_code == 200 and answer.json() == {"user": "learner"}
    assert browser.get("/api/me/").json() == {"user": "learner", "is_staff": False, "approved": True,
                                              "site_origin": "http://testserver:8002"}


def test_me_names_the_configured_site_origin_the_site_pane_loads_from(browser, learner, monkeypatch):
    monkeypatch.setenv("CR_SITE_ORIGIN", "https://Site.Example/")
    sign_in(browser, "learner")

    assert browser.get("/api/me/").json()["site_origin"] == "https://site.example"


def test_me_tells_staff_apart(browser, staff):
    sign_in(browser, "operator")

    assert browser.get("/api/me/").json()["is_staff"] is True


@pytest.mark.parametrize("username, password", [("learner", "wrong-password-0"), ("nobody", PASSWORD)])
def test_a_wrong_password_and_an_unknown_user_get_the_same_refusal(browser, learner, username, password):
    refused(sign_in(browser, username, password), 401, "wrong_credentials")


def test_an_account_waiting_for_approval_is_told_so_only_with_its_own_password(browser, make_user):
    make_user("waiting", active=False)

    refused(sign_in(browser, "waiting"), 403, "account_pending")
    refused(sign_in(browser, "waiting", "wrong-password-0"), 401, "wrong_credentials")


def test_a_sign_up_waits_for_a_staff_approval_before_it_can_sign_in(browser, staff):
    answer = sign_up(browser, "newcomer")

    assert answer.status_code == 201 and answer.json() == {"user": "newcomer", "approved": False}
    refused(sign_in(browser, "newcomer", STRONG), 403, "account_pending")

    newcomer = get_user_model().objects.get(username="newcomer")
    staff_client = APIClient()
    staff_client.force_authenticate(staff)
    assert staff_client.post(f"/api/staff/users/{newcomer.username}/approve/").json()["approved"] is True

    assert sign_in(browser, "newcomer", STRONG).status_code == 200


def test_a_taken_username_is_refused_whatever_its_case(browser, learner):
    refused(sign_up(browser, "LEARNER"), 400, "username_taken", path="username")


def test_a_weak_password_names_each_rule_it_breaks(browser):
    found = refused(sign_up(browser, "newcomer", "1234"), 400, "password_too_short", path="password")
    refused(sign_up(browser, "newcomer", "1234"), 400, "password_entirely_numeric", path="password")

    assert found["params"] == {"min_length": 8}


def test_a_username_with_other_characters_is_invalid(browser):
    refused(sign_up(browser, "two words"), 400, "invalid", path="username")


def test_missing_fields_are_required_by_path(browser):
    answer = browser.post("/api/auth/signup/", {}, format="json")

    refused(answer, 400, "required", path="username")
    refused(answer, 400, "required", path="password")


def test_one_address_signs_up_at_most_five_times_an_hour(browser):
    for number in range(signin.SIGN_UPS_PER_ADDRESS_PER_HOUR):
        assert sign_up(browser, f"newcomer{number}").status_code == 201

    answer = sign_up(browser, "one-too-many")

    refused(answer, 429, "sign_ups_throttled")
    assert answer["Retry-After"] == "3600"
    assert not get_user_model().objects.filter(username="one-too-many").exists()


def test_sign_up_closes_while_too_many_accounts_wait(browser, make_user, monkeypatch):
    monkeypatch.setattr(signin, "PENDING_AT_MOST", 2)
    make_user("waiting1", active=False)
    make_user("waiting2", active=False)

    refused(sign_up(browser, "newcomer"), 503, "sign_ups_closed")


def test_signing_out_ends_the_session(browser, learner):
    sign_in(browser, "learner")

    assert browser.post("/api/auth/logout/").status_code == 204
    refused(browser.get("/api/me/"), 401, "not_signed_in")


def test_a_session_request_without_the_csrf_token_is_refused(db, forget_counts, learner):
    strict = APIClient(enforce_csrf_checks=True, REMOTE_ADDR=CALLER)

    refused(sign_in(strict, "learner"), 403, "csrf_failed")

    token = strict.get("/api/auth/csrf/").cookies["cr_csrf"].value
    strict.credentials(HTTP_X_CSRFTOKEN=token)
    assert sign_in(strict, "learner").status_code == 200

    strict.credentials()
    refused(strict.post("/api/auth/logout/"), 403, "csrf_failed")
    strict.credentials(HTTP_X_CSRFTOKEN=strict.cookies["cr_csrf"].value)
    assert strict.post("/api/auth/logout/").status_code == 204


def test_a_csrf_refusal_leaves_the_request_anonymous_rather_than_failing_again_on_each_read(db, learner):
    from django.contrib.auth.models import AnonymousUser
    from django.contrib.sessions.backends.db import SessionStore
    from rest_framework import exceptions
    from rest_framework.request import Request
    from rest_framework.test import APIRequestFactory

    sent = APIRequestFactory(enforce_csrf_checks=True).post("/api/auth/logout/", {}, format="json")
    sent.session, sent.user = SessionStore(), learner
    request = Request(sent, authenticators=[users.SessionAuthentication()])

    with pytest.raises(exceptions.PermissionDenied) as refused:
        request.user

    assert refused.value.get_codes() == "csrf_failed"
    assert isinstance(request.user, AnonymousUser)
